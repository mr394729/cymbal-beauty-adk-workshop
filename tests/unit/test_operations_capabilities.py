"""Business-state and access tests for the expanded store workflows."""
import asyncio
import threading

import pytest
from google.adk.events import Event
from google.genai import types

from agents.cymbal_store_ops.chat_reply import ChatReplyPlugin
from agents.cymbal_store_ops.tools import domain_tools as domain
from agents.cymbal_store_ops.tools.operations_tools import concurrent_read, get_learning_options
from agents.cymbal_store_ops.tools.personal_tools import (
    complete_my_task,
    get_coaching_context,
    get_my_work,
)
from tests.conftest import FakeToolContext


def ctx(role="associate", uid="A-1004", confirmed=None):
    return FakeToolContext({"user:role": role, "user:user_id": uid, "user:store_id": "S-014"}, confirmed=confirmed)


def test_assignment_changes_next_coverage_recommendation(fake_backend):
    manager = ctx("store_manager", "U-M014", True)
    before = domain.get_shift_roster(tool_context=manager)
    assert before["recommended_assignee_id"] == "A-1004"
    result = domain.create_store_task("backroom_check", "Pick four Hydra units before 9:30", "P-0101", "Priya", tool_context=manager)
    assert result["status"] == "SUCCESS"
    after = domain.get_shift_roster(tool_context=manager)
    assert after["recommended_assignee_id"] == "A-1000"
    priya = next(r for r in after["rows"] if r["associate_id"] == "A-1004")
    assert priya["assigned_tasks"][0]["task_id"] == result["rows"][0]["task_id"]


def test_coaching_has_dated_units_and_self_scope(fake_backend):
    r = get_coaching_context("Noor", ctx("store_manager", "U-M014"))
    shift = r["shift_activity"][0]["payload"]
    assert shift["picks_completed"] == 23 and shift["picks_within_target"] == 12
    assert shift["date"] == "2026-10-02" and shift["target_minutes"] == 8
    assert get_coaching_context("Noor", ctx())["code"] == "forbidden"
    assert get_learning_options("Noor", ctx())["code"] == "forbidden"
    assert get_coaching_context("", ctx())["associate"]["associate_id"] == "A-1004"
    assert get_learning_options("", ctx())["rows"][0]["subject_id"] == "A-1004"
    assert get_coaching_context("A-1008", ctx("store_manager", "U-M014"))["status"] == "ERROR"


def test_completion_requires_own_task_and_confirmation_and_is_idempotent(fake_backend):
    manager = ctx("store_manager", "U-M014", True)
    task = domain.create_store_task("replenish", "Replenish the display", "P-0101", "Priya", tool_context=manager)["rows"][0]
    tid = task["task_id"]
    pending = complete_my_task(tid, "Moved three units to the display", ctx())
    assert pending["status"] != "SUCCESS"
    assert next(t for t in fake_backend.tasks if t["task_id"] == tid)["status"] == "open"
    assert complete_my_task(tid, "Done", ctx(uid="A-1000", confirmed=True))["code"] == "forbidden"
    assert complete_my_task(tid, "Moved three units", ctx(confirmed=False))["status"] != "SUCCESS"
    result = complete_my_task(tid, "Moved three units", ctx(confirmed=True))
    assert result["rows"][0]["status"] == "done"
    assert complete_my_task(tid, "Duplicate", ctx(confirmed=True))["already_completed"]
    assert result["rows"][0]["note"].count("Completion:") == 1
    assert get_my_work(ctx())["rows"][0]["task_id"] == tid
    stock = domain.check_store_stock("Lumière Hydra Cream", tool_context=ctx())
    assert stock["rows"][0]["on_shelf_qty"] == 0  # Completion is not an inventory movement.


@pytest.mark.asyncio
async def test_read_adapter_actually_allows_two_blocking_reads_in_parallel():
    barrier = threading.Barrier(2)
    def blocking_read(value: int) -> int:
        barrier.wait(timeout=2)
        return value
    read = concurrent_read(blocking_read)
    assert await asyncio.gather(read(1), read(2)) == [1, 2]


@pytest.mark.asyncio
async def test_structured_reply_separates_answer_and_actions():
    import json
    payload = {"answer": "Priya is already assigned. Jordan can cover picking.", "next_actions": [
        {"label": label, "prompt": prompt} for label, prompt in [
            ("Review Jordan's shift", "Show Jordan's shift and assigned work."),
            ("Check pickup deadlines", "Which pickup orders are due first?"),
            ("Review floor coverage", "Show the floor coverage requirements until 11.")]]}
    event = Event(author="store_manager_agent", content=types.Content(role="model", parts=[types.Part(text=json.dumps(payload))]))
    shaped = await ChatReplyPlugin().on_event_callback(invocation_context=None, event=event)
    assert shaped.content.parts[0].text == payload["answer"]
    assert len(shaped.actions.state_delta["ui:next_actions"]) == 3
    from frontend.server import shape
    messages = shape(shaped.model_dump(mode="json", exclude_none=True))
    assert [x["text"] for x in messages if x["type"] == "text"] == [payload["answer"]]
    specialist = Event(author="inventory_excellence", content=types.Content(role="model", parts=[types.Part(text="Inventory working result")]))
    assert shape(specialist.model_dump(mode="json", exclude_none=True))[0]["type"] == "agent_note"


def test_raw_sql_cannot_read_personal_operational_snapshots():
    from agents.cymbal_store_ops.tools.sql_guard import SqlGuardError, assert_select_only
    with pytest.raises(SqlGuardError):
        assert_select_only("SELECT * FROM `p.d.operations_context`", ["p.d"])


def test_parallel_read_order_preserves_write_dependencies():
    from eval.metrics import _in_dependency_order
    expected = ["associate_orchestration", "get_traffic_and_backlog", "get_shift_roster", "create_store_task"]
    assert _in_dependency_order(expected, ["associate_orchestration", "get_shift_roster", "get_traffic_and_backlog", "create_store_task"])
    assert not _in_dependency_order(expected, ["get_shift_roster", "associate_orchestration", "get_traffic_and_backlog", "create_store_task"])
    assert not _in_dependency_order(expected, ["associate_orchestration", "get_shift_roster", "create_store_task", "get_traffic_and_backlog"])


def test_pickup_task_deadline_is_reviewed_and_persisted(fake_backend):
    pending = ctx("store_manager", "U-M014")
    due = "2026-10-03T09:30:00-05:00"
    result = domain.create_store_task("backroom_check", "Pick four units", "P-0101", "Priya", due_at=due, tool_context=pending)
    assert result["status"] != "SUCCESS"
    assert pending.confirmation_requests[0]["payload"]["due_at"] == due
    approved = ctx("store_manager", "U-M014", True)
    result = domain.create_store_task("backroom_check", "Pick four units", "P-0101", "Priya", due_at=due, tool_context=approved)
    assert result["rows"][0]["due_at"] == "2026-10-03T09:30-05:00"
    assert domain.create_store_task("backroom_check", "Pick", due_at="2026-10-03T08:00:00-05:00", tool_context=approved)["status"] == "ERROR"


def test_blocker_requires_confirmation_and_ownership_and_is_visible_once_to_manager(fake_backend):
    from agents.cymbal_store_ops.tools.personal_tools import report_my_task_blocker

    manager = ctx("store_manager", "U-M014", True)
    task = domain.create_store_task("backroom_check", "Pick Hydra Cream", "P-0101", "Priya", tool_context=manager)["rows"][0]
    tid = task["task_id"]
    note = "Recorded bin is empty; stock location needs review"
    pending = ctx()
    assert report_my_task_blocker(tid, note, pending)["status"] != "SUCCESS"
    assert pending.confirmation_requests[0]["payload"] == {"task_id": tid, "blocker": note}
    assert report_my_task_blocker(tid, note, ctx(confirmed=False))["status"] != "SUCCESS"
    assert report_my_task_blocker(tid, note, ctx(uid="A-1000", confirmed=True))["code"] == "forbidden"
    untouched = next(t for t in fake_backend.tasks if t["task_id"] == tid)
    assert "Blocker:" not in untouched["note"] and untouched["status"] == "open"

    first = report_my_task_blocker(tid, note, ctx(confirmed=True))
    retry = report_my_task_blocker(tid, note, ctx(confirmed=True))
    assert first["status"] == "SUCCESS" and not first["already_reported"]
    assert retry["already_reported"] and retry["rows"][0]["note"].count(note) == 1
    assert retry["rows"][0]["status"] == "open"
    manager_view = domain.get_task_status("P-0101", tool_context=manager)["rows"]
    assert next(t for t in manager_view if t["task_id"] == tid)["note"].count(note) == 1
    roster = domain.get_shift_roster(tool_context=manager)
    assert roster["recommended_assignee_id"] != "A-1004"
    stock = domain.check_store_stock("P-0101", tool_context=manager)["rows"][0]
    assert stock["on_hand"] == 7 and stock["backroom_qty"] == 7


def test_blocker_rejects_empty_closed_and_cross_store_work(fake_backend):
    from agents.cymbal_store_ops.tools.personal_tools import report_my_task_blocker

    manager = ctx("store_manager", "U-M014", True)
    task = domain.create_store_task("backroom_check", "Review location", "P-0101", "Priya", tool_context=manager)["rows"][0]
    tid = task["task_id"]
    assert report_my_task_blocker(tid, "  ", ctx(confirmed=True))["status"] == "ERROR"
    other_store = ctx(confirmed=True)
    other_store.state["user:store_id"] = "S-002"
    assert report_my_task_blocker(tid, "Issue", other_store)["code"] == "forbidden"
    assert complete_my_task(tid, "Located the stock", ctx(confirmed=True))["status"] == "SUCCESS"
    assert report_my_task_blocker(tid, "Issue", ctx(confirmed=True))["code"] == "conflict"


def test_guest_product_stock_joins_exact_sku_even_when_display_names_are_shared(fake_backend):
    from agents.cymbal_store_ops.tools.operations_tools import get_guest_product_options

    # A catalog display name is not a SKU. Two valid products with the same name must retain
    # their own stock; the no-fragrance-preference default must include both product types.
    products = fake_backend.products[:2]
    for product, fragrance_free in zip(products, (True, False), strict=True):
        product["name"] = "Shared guest product name"
        product["is_fragrance_free"] = fragrance_free
    result = get_guest_product_options(query_text="Shared guest product name", tool_context=ctx())
    assert result["status"] == "SUCCESS" and len(result["rows"]) == 2
    assert {row["product"]["product_id"] for row in result["rows"]} == {p["product_id"] for p in products}
    for row in result["rows"]:
        assert len(row["stock"]) == 1
        assert row["stock"][0]["product_id"] == row["product"]["product_id"]
    stock_queries = [args for name, args in fake_backend.calls if name == "check_store_stock"]
    assert {query["product_name"] for query in stock_queries} == {p["product_id"] for p in products}


def test_guest_product_options_report_the_catalog_count_not_the_page(fake_backend):
    """Three products are shown; `matching` is how many qualify in the whole catalog, so the answer can say "three of N"."""
    from agents.cymbal_store_ops.tools.operations_tools import get_guest_product_options

    qualifying = [p for p in fake_backend.products if p["category"] == "skincare"]
    assert len(qualifying) > 3
    result = get_guest_product_options(category="skincare", tool_context=ctx())
    assert result["status"] == "SUCCESS" and result["shown"] == 3 and len(result["rows"]) == 3
    assert result["matching"] == len(qualifying) and result["more_qualify"] is True
