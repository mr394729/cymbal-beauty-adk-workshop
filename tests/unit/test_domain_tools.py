"""Every domain tool against the in-memory backend: envelopes, store scope, the three recommendation rules,
the two writes (idempotent, conflict-safe), the fault switches and the demo identity."""
import sys
from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import ROOT, FakeToolContext

sys.path.insert(0, str(ROOT / "data"))
import fixtures as F  # noqa: E402

NOW = datetime.fromisoformat(F.FIXTURE_NOW_ISO)


@pytest.fixture
def manager(fake_backend):
    """A session signed in as the hero store's manager."""
    from agents.cymbal_store_ops.tools.domain_tools import identify_demo_user
    ctx = FakeToolContext(confirmed=True)   # the manager has already approved any write in these tests
    assert identify_demo_user(F.HERO_MANAGER_ID, ctx)["status"] == "SUCCESS"
    return ctx


def _set_fault(monkeypatch, fault: str) -> None:
    from agents.cymbal_store_ops import config
    monkeypatch.setenv("STORE_OPS_FAULT", fault)
    config.load_env_config.cache_clear()


# ---- identity ---------------------------------------------------------------------------------------
def test_identify_demo_user_seeds_state_from_associates(fake_backend):
    from agents.cymbal_store_ops.tools.domain_tools import identify_demo_user
    ctx = FakeToolContext()
    r = identify_demo_user(F.HERO_MANAGER_ID, ctx)
    assert r["status"] == "SUCCESS" and r["rows"][0]["role"] == "store_manager"
    assert ctx.state == {"user:user_id": F.HERO_MANAGER_ID, "user:store_id": F.HERO_STORE_ID,
                         "user:role": "store_manager", "user:first_name": F.HERO_MANAGER_FIRST_NAME}
    ctx2 = FakeToolContext()
    assert identify_demo_user(F.HERO_DISTRICT_MANAGER_ID, ctx2)["rows"][0]["role"] == "district_manager"
    assert ctx2.state["user:store_id"] == F.HERO_STORE_ID
    assert identify_demo_user(F.HERO_ASSOCIATE_ID, FakeToolContext())["rows"][0]["first_name"] == F.HERO_ASSOCIATE_FIRST_NAME
    bad = identify_demo_user("nobody", FakeToolContext())
    assert bad["status"] == "ERROR" and F.HERO_MANAGER_ID in bad["error_details"]


def test_store_scope_comes_from_state_not_arguments(fake_backend, manager):
    from agents.cymbal_store_ops.tools.domain_tools import get_osa_exceptions
    assert get_osa_exceptions()["status"] == "ERROR"                       # nobody signed in, no store given
    assert get_osa_exceptions(tool_context=manager)["rows"][0]["store_id"] == F.HERO_STORE_ID
    assert get_osa_exceptions(store_id="S-002")["rows"][0]["store_id"] == "S-002"   # explicit (district manager)


# ---- catalog ----------------------------------------------------------------------------------------
def test_search_products_envelope_and_filters(fake_backend):
    from agents.cymbal_store_ops.tools.domain_tools import search_products
    r = search_products(query_text="moisturizer", fragrance_free=True, skin_type="sensitive", max_price=30, limit=5)
    assert r["status"] == "SUCCESS" and 1 <= len(r["rows"]) <= 5
    assert all(row["is_fragrance_free"] and row["price_usd"] <= 30 for row in r["rows"])
    assert set(r["rows"][0]) >= {"product_id", "brand", "name", "price_usd", "rating_avg", "locked_case"}
    # the envelope counts the whole catalog match, whatever the page size
    assert r["total_matching"] >= len(r["rows"])
    one = search_products(query_text="moisturizer", fragrance_free=True, skin_type="sensitive", max_price=30, limit=1)
    assert len(one["rows"]) == 1 and one["total_matching"] == r["total_matching"]


def test_hero_product_is_findable(fake_backend):
    from agents.cymbal_store_ops.tools.domain_tools import get_product_details, search_products
    r = search_products(query_text="Hydra Cream", limit=3)
    assert any(row["product_id"] == F.HERO_PRODUCT_ID for row in r["rows"])
    d = get_product_details(F.HERO_PRODUCT_ID)
    assert d["rows"][0]["name"] == F.HERO_PRODUCT_NAME and "top_reviews" in d["rows"][0]
    assert get_product_details(F.SHRINK_PRODUCT_ID)["rows"][0]["locked_case"] is True


# ---- inventory excellence ---------------------------------------------------------------------------
def test_check_store_stock_hero_fixture_and_rule(fake_backend, manager):
    from agents.cymbal_store_ops.tools.domain_tools import check_store_stock
    r = check_store_stock(F.HERO_PRODUCT_NAME, tool_context=manager)
    row = next(x for x in r["rows"] if x["product_id"] == F.HERO_PRODUCT_ID)
    assert (row["store_id"], row["on_hand"], row["on_shelf_qty"], row["backroom_qty"], row["reorder_point"], row["shelf_capacity"]) == \
        (F.HERO_STORE_ID, F.HERO_STORE_ON_HAND, F.HERO_STORE_ON_SHELF, F.HERO_STORE_BACKROOM, F.HERO_REORDER_POINT, F.HERO_SHELF_CAPACITY)
    assert row["recommended_actions"] == ["backroom_check", "replenish"] and row["recommendation"] == "backroom_check"
    assert row["replenishment_in_transit"] is False and row["is_osa_exception"] is True


def test_check_store_stock_by_city_keeps_the_quickstart_contract(fake_backend):
    from agents.cymbal_store_ops.tools.domain_tools import check_store_stock
    r = check_store_stock("Lumière Hydra Cream", "Naperville")
    row = next(x for x in r["rows"] if x["product_id"] == F.HERO_PRODUCT_ID)
    assert row["store_name"] == F.HERO_STORE_NAME and row["on_hand"] == F.HERO_STORE_ON_HAND
    assert fake_backend.calls[-1][0] == "check_store_stock" and fake_backend.calls[-2][0] == "get_replenishment_status"
    r = check_store_stock("Hydra Cream", "Atlantis")
    assert r["status"] == "ERROR" and "Atlantis" in r["error_details"]
    assert check_store_stock("No Such Product", store_id=F.HERO_STORE_ID)["status"] == "ERROR"


def test_osa_exceptions_put_the_hero_first_with_recommendations(fake_backend, manager):
    from agents.cymbal_store_ops.tools.domain_tools import get_osa_exceptions
    r = get_osa_exceptions(limit=10, tool_context=manager)
    assert r["status"] == "SUCCESS" and len(r["rows"]) == 10 and r["result_is_likely_truncated"]
    first = r["rows"][0]
    assert first["product_id"] == F.HERO_PRODUCT_ID and first["exception_type"] == "shelf_empty"
    assert first["recommendation"] == "backroom_check"
    assert all(row["recommendation"] in ("backroom_check", "replenish", "cycle_count", "escalate") for row in r["rows"])


@pytest.mark.parametrize("position,repl,expected", [
    ({"on_hand": 7, "on_shelf_qty": 0, "backroom_qty": 7, "reorder_point": 12}, [], ["backroom_check", "replenish"]),
    ({"on_hand": 7, "on_shelf_qty": 0, "backroom_qty": 7, "reorder_point": 12}, [{"product_id": "P-X", "status": "in_transit"}], ["backroom_check"]),
    ({"on_hand": 2, "on_shelf_qty": 2, "backroom_qty": 0, "reorder_point": 6}, [{"product_id": "P-X", "status": "scheduled"}], ["replenish"]),
    ({"on_hand": 3, "on_shelf_qty": 0, "backroom_qty": 0, "reorder_point": 2}, [], ["cycle_count"]),
    ({"on_hand": 1, "on_shelf_qty": 1, "backroom_qty": 0, "reorder_point": 4}, [{"product_id": "P-X", "status": "in_transit"}], ["escalate"]),
    ({"on_hand": 9, "on_shelf_qty": 6, "backroom_qty": 3, "reorder_point": 4}, [], []),
])
def test_osa_rule_table(position, repl, expected):
    from agents.cymbal_store_ops.tools.domain_tools import osa_recommendation
    out = osa_recommendation({"product_id": "P-X", **position}, repl)
    assert out["recommended_actions"] == expected
    assert out["recommendation"] == (expected[0] if expected else "none")
    assert out["is_osa_exception"] is bool(expected)


def test_bopis_demand_replenishment_and_tasks(fake_backend, manager):
    from agents.cymbal_store_ops.tools.domain_tools import (
        get_bopis_demand,
        get_replenishment_status,
        get_task_status,
    )
    r = get_bopis_demand(tool_context=manager)
    assert r["pending_count"] == F.HERO_BOPIS_PENDING and len(r["rows"]) == F.HERO_BOPIS_PENDING
    assert all(o["status"] == "pending" and o["store_id"] == F.HERO_STORE_ID for o in r["rows"])
    assert get_bopis_demand(product_id=F.HERO_PRODUCT_ID, tool_context=manager)["pending_count"] == F.HERO_BOPIS_PENDING_FOR_PRODUCT
    assert get_bopis_demand(hours=1, tool_context=manager)["pending_count"] < F.HERO_BOPIS_PENDING
    repl = get_replenishment_status(product_id=F.HERO_PRODUCT_ID, tool_context=manager)
    assert [x["status"] for x in repl["rows"]] == ["delayed"]
    assert get_task_status(product_id=F.HERO_PRODUCT_ID, tool_context=manager)["rows"] == []
    assert all(t["status"] == "open" for t in get_task_status(tool_context=manager)["rows"])
    assert get_task_status(status="bogus", tool_context=manager)["status"] == "ERROR"


def test_find_nearby_stock_stays_in_state(fake_backend, manager):
    from agents.cymbal_store_ops.tools.domain_tools import find_nearby_stock
    r = find_nearby_stock("Hydra Cream", tool_context=manager)
    assert r["rows"] and all(x["state"] == "IL" and x["store_id"] != F.HERO_STORE_ID and x["on_hand"] > 0 for x in r["rows"])


# ---- associate orchestration ------------------------------------------------------------------------
def test_coverage_rule_recommends_priya(fake_backend, manager):
    from agents.cymbal_store_ops.tools.domain_tools import get_shift_roster
    r = get_shift_roster(tool_context=manager)
    assert r["status"] == "SUCCESS" and r["focus"] == "bopis"
    on_shift = {x["associate_id"] for x in r["rows"]}
    assert {F.HERO_ASSOCIATE_ID, F.HERO_MANAGER_ID, F.COACHING_ASSOCIATE_ID} <= on_shift and "A-1003" not in on_shift
    assert r["recommended_assignee_id"] == F.HERO_ASSOCIATE_ID
    cands = r["candidates"]
    assert [c["associate_id"] for c in cands] == [F.HERO_ASSOCIATE_ID, "A-1000"]      # free + bopis, earliest shift end first
    assert all(c["covers_window"] and not c["current_task"] and "bopis" in c["skills"] for c in cands)
    assert F.COACHING_ASSOCIATE_ID not in [c["associate_id"] for c in cands]         # busy at the cash wrap
    later = get_shift_roster(window_hours=8, tool_context=manager)                     # Priya leaves at 13:00
    assert later["recommended_assignee_id"] == "A-1000" and later["candidates"][-1]["associate_id"] == F.HERO_ASSOCIATE_ID
    assert get_shift_roster(focus="haircare", tool_context=manager)["recommended_assignee_id"] == ""  # Chloe has assigned planogram work.
    assert get_shift_roster(focus="juggling", tool_context=manager)["status"] == "ERROR"


def test_coverage_rule_directly():
    from agents.cymbal_store_ops.tools.domain_tools import coverage_candidates
    end = NOW + timedelta(hours=4)
    roster = [
        {"associate_id": "A-1", "role": "associate", "skills": ["bopis"], "current_task": None, "shift_end": (NOW + timedelta(hours=8)).isoformat()},
        {"associate_id": "A-2", "role": "associate", "skills": ["bopis"], "current_task": None, "shift_end": (NOW + timedelta(hours=4)).isoformat()},
        {"associate_id": "A-3", "role": "associate", "skills": ["bopis"], "current_task": None, "shift_end": (NOW + timedelta(hours=2)).isoformat()},
        {"associate_id": "A-4", "role": "associate", "skills": ["bopis"], "current_task": "cash wrap", "shift_end": (NOW + timedelta(hours=8)).isoformat()},
        {"associate_id": "A-5", "role": "associate", "skills": ["makeup"], "current_task": None, "shift_end": (NOW + timedelta(hours=8)).isoformat()},
        {"associate_id": "U-M1", "role": "store_manager", "skills": ["bopis"], "current_task": None, "shift_end": (NOW + timedelta(hours=8)).isoformat()},
    ]
    assert [c["associate_id"] for c in coverage_candidates(roster, focus="bopis", window_end=end)] == ["A-2", "A-1", "A-3"]


def test_traffic_and_backlog_window(fake_backend, manager):
    from agents.cymbal_store_ops.tools.domain_tools import get_traffic_and_backlog
    r = get_traffic_and_backlog(tool_context=manager)
    assert [x["visitors"] for x in r["rows"]] == [40, 72, 88, 80] and r["pending_bopis"] == F.HERO_BOPIS_PENDING
    assert r["window_start"] == NOW.isoformat(timespec="minutes")
    assert all(x["ts_hour"].endswith("-05:00") for x in r["rows"]), "traffic hours must be store-local"
    assert len(get_traffic_and_backlog(hours=2, tool_context=manager)["rows"]) == 2


def test_times_reach_the_model_in_store_local_time(fake_backend, manager):
    """The tables hold UTC; a manager asking 'who is free until 11' must read 09:00-05:00, not 14:00+00:00."""
    from agents.cymbal_store_ops.tools.domain_tools import get_shift_roster
    r = get_shift_roster(tool_context=manager)
    times = [row[k] for row in r["rows"] for k in ("shift_start", "shift_end")]
    assert times and all(t.endswith("-05:00") for t in times), times[:4]
    assert not any("+00:00" in str(v) for v in r.values() if isinstance(v, str))


# ---- loss prevention --------------------------------------------------------------------------------
def test_shrink_rule_flags_the_locked_case_fragrance(fake_backend, manager):
    from agents.cymbal_store_ops.tools.domain_tools import get_shrink_signals, shrink_recommendation
    r = get_shrink_signals(tool_context=manager)
    top = r["products"][0]
    assert top["product_id"] == F.SHRINK_PRODUCT_ID and top["events"] == F.SHRINK_EVENTS_14D and top["recommendation"] == "investigate"
    assert top["locked_case"] is True and top["value_usd"] >= 250
    assert all(p["recommendation"] == "monitor" for p in r["products"][1:] if p["events"] < 5 and p["value_usd"] < 250)
    assert all(key not in row for row in r["rows"] for key in ("associate_id", "first_name", "assignee_id"))
    only = get_shrink_signals(product_id=F.SHRINK_PRODUCT_ID, tool_context=manager)
    assert {x["product_id"] for x in only["rows"]} == {F.SHRINK_PRODUCT_ID} and only["products"][0]["events"] == F.SHRINK_EVENTS_14D
    assert get_shrink_signals(product_id=F.SHRINK_PRODUCT_ID, days=28, tool_context=manager)["products"][0]["events"] == F.SHRINK_EVENTS_14D + 2
    assert shrink_recommendation(5, 10.0) == "investigate" and shrink_recommendation(1, 250.0) == "investigate"
    assert shrink_recommendation(4, 249.99) == "monitor"


def test_sales_pattern_and_task_history(fake_backend, manager):
    from agents.cymbal_store_ops.tools.domain_tools import get_sales_pattern, get_task_history
    s = get_sales_pattern(product_id=F.SHRINK_PRODUCT_ID, tool_context=manager)
    assert len(s["rows"]) == 14 and s["rows"][-1]["day"] == F.FIXTURE_NOW_ISO[:10] and s["product_id"] == F.SHRINK_PRODUCT_ID
    assert all(set(d) == {"day", "visitors", "transactions", "sales_usd"} for d in s["rows"])
    h = get_task_history(product_id=F.SHRINK_PRODUCT_ID, tool_context=manager)
    assert [t["task_type"] for t in h["rows"]] == ["investigation"] and h["rows"][0]["status"] == "done"
    assert len(get_task_history(tool_context=manager)["rows"]) == 10


# ---- daily briefing and associate development -------------------------------------------------------
def test_guest_feedback_summary(fake_backend, manager):
    from agents.cymbal_store_ops.tools.domain_tools import get_guest_feedback
    r = get_guest_feedback(tool_context=manager)
    assert r["summary"]["low_ratings_by_topic"]["checkout_wait"] == 2 and r["summary"]["count"] == len(r["rows"])
    assert all(set(f) >= {"rating", "topic", "comment"} and "@" not in f["comment"] for f in r["rows"])


def test_coaching_signals_role_and_store_gate(fake_backend, manager):
    from agents.cymbal_store_ops.tools.domain_tools import get_coaching_signals, identify_demo_user
    r = get_coaching_signals(F.COACHING_ASSOCIATE_ID, tool_context=manager)
    pick = next(x for x in r["rows"] if x["metric"] == "bopis_pick_rate")
    assert pick["period"] == F.FIXTURE_WEEK and pick["value"] < 0.6 and r["associate"]["store_id"] == F.HERO_STORE_ID
    assert len(get_coaching_signals(F.COACHING_ASSOCIATE_ID, period=F.FIXTURE_WEEK, tool_context=manager)["rows"]) == 4
    assert get_coaching_signals("A-1010", tool_context=manager)["code"] == "forbidden"      # another store
    dm = FakeToolContext()
    identify_demo_user(F.HERO_DISTRICT_MANAGER_ID, dm)
    assert get_coaching_signals("A-1010", tool_context=dm)["status"] == "SUCCESS"            # district manager may
    assoc = FakeToolContext()
    identify_demo_user(F.HERO_ASSOCIATE_ID, assoc)
    assert get_coaching_signals(F.COACHING_ASSOCIATE_ID, tool_context=assoc)["status"] == "ERROR"
    assert get_coaching_signals("A-9999", tool_context=manager)["code"] == "not_found"


# ---- the writes -------------------------------------------------------------------------------------
def test_create_store_task_is_idempotent_and_scoped(fake_backend, manager):
    from agents.cymbal_store_ops.tools.domain_tools import create_store_task, get_task_status
    first = create_store_task("backroom_check", "Move the 7 backroom units to the shelf.", F.HERO_PRODUCT_ID, F.HERO_ASSOCIATE_ID, tool_context=manager.new_request())
    assert first["status"] == "SUCCESS" and first["already_created"] is False
    task = first["rows"][0]
    assert task["store_id"] == F.HERO_STORE_ID and task["status"] == "open" and task["source"] == "agent"
    assert task["assignee_id"] == F.HERO_ASSOCIATE_ID and task["task_id"].startswith("T-")
    from tests.conftest import FakeToolContext
    fresh = FakeToolContext(state={k: v for k, v in manager.state.items() if not k.startswith(("temp:", "writes:"))},
                            confirmed=True)   # a later message: temp state gone, as ADK does between invocations
    again = create_store_task("backroom_check", "Move the 7 backroom units to the shelf.", F.HERO_PRODUCT_ID, F.HERO_ASSOCIATE_ID, tool_context=fresh)
    assert again["already_created"] is True and again["rows"][0]["task_id"] == task["task_id"]
    assert sum(1 for c in fake_backend.calls if c[0] == "create_store_task") == 2
    assert len([t for t in fake_backend.tasks if t["task_key"]]) == 1
    assert get_task_status(product_id=F.HERO_PRODUCT_ID, tool_context=manager)["rows"][0]["task_id"] == task["task_id"]
    other = create_store_task("replenish", "Different note.", F.HERO_PRODUCT_ID, "", tool_context=manager.new_request())
    assert other["already_created"] is False and other["rows"][0]["task_id"] != task["task_id"]
    assert create_store_task("juggle", "x", tool_context=manager.new_request())["status"] == "ERROR"
    assert create_store_task("replenish", "x", "P-9999", "", tool_context=manager.new_request())["code"] == "not_found"
    assert create_store_task("replenish", "x", "", "A-1010", tool_context=manager.new_request())["code"] == "not_found"
    assert create_store_task("replenish", "x", tool_context=FakeToolContext())["status"] == "ERROR"   # no store in scope
    assert create_store_task("replenish", "x")["status"] == "ERROR"


def test_delegate_task_only_touches_open_tasks(fake_backend, manager):
    from agents.cymbal_store_ops.tools.domain_tools import delegate_task
    open_task = next(t for t in fake_backend.tasks if t["store_id"] == F.HERO_STORE_ID and t["status"] == "open")
    done_task = next(t for t in fake_backend.tasks if t["store_id"] == F.HERO_STORE_ID and t["status"] == "done")
    r = delegate_task(open_task["task_id"], F.HERO_ASSOCIATE_ID, manager.new_request())
    assert r["status"] == "SUCCESS" and r["rows"][0]["assignee_id"] == F.HERO_ASSOCIATE_ID and r["already_delegated"] is False
    again = delegate_task(open_task["task_id"], F.HERO_ASSOCIATE_ID, manager.new_request())
    assert again["already_delegated"] is True and again["rows"][0]["assignee_id"] == F.HERO_ASSOCIATE_ID
    conflict = delegate_task(done_task["task_id"], F.HERO_ASSOCIATE_ID, manager.new_request())
    assert conflict["status"] == "ERROR" and conflict["code"] == "conflict"
    assert delegate_task(open_task["task_id"], "A-1010", manager.new_request())["code"] == "not_found"        # not at this store
    assert delegate_task("T-99999", F.HERO_ASSOCIATE_ID, manager.new_request())["code"] == "not_found"
    foreign = FakeToolContext({"user:store_id": "S-002", "user:role": "store_manager"}, confirmed=True)
    assert delegate_task(open_task["task_id"], F.HERO_ASSOCIATE_ID, foreign)["code"] == "not_found"  # scoped by state


# ---- fault switches ---------------------------------------------------------------------------------
def test_stale_stock_fault_is_deterministic(fake_backend, manager, monkeypatch):
    from agents.cymbal_store_ops.tools.domain_tools import check_store_stock, get_osa_exceptions
    _set_fault(monkeypatch, "stale_stock")
    r = check_store_stock(F.HERO_PRODUCT_NAME, tool_context=manager)
    row = next(x for x in r["rows"] if x["product_id"] == F.HERO_PRODUCT_ID)
    assert row["on_hand"] == F.HERO_STORE_ON_HAND + 5 and r["fault_injected"] == "stale_stock"
    assert row["backroom_qty"] == F.HERO_STORE_BACKROOM + 5                     # the feed is stale as a whole
    assert row["recommended_actions"] == ["backroom_check"]                    # the stale count hides the replenish
    hero = next(x for x in get_osa_exceptions(tool_context=manager)["rows"] if x["product_id"] == F.HERO_PRODUCT_ID)
    assert hero["on_hand"] == F.HERO_STORE_ON_HAND + 5


def test_stale_backlog_fault_removes_the_pending_signal(fake_backend, manager, monkeypatch):
    from agents.cymbal_store_ops.tools.domain_tools import get_bopis_demand, get_traffic_and_backlog
    _set_fault(monkeypatch, "stale_backlog")
    d = get_bopis_demand(tool_context=manager)
    assert d["status"] == "SUCCESS" and d["pending_count"] == 0 and d["rows"] == []
    assert d["fault_injected"] == "stale_backlog"
    t = get_traffic_and_backlog(tool_context=manager)
    assert t["pending_bopis"] == 0 and t["fault_injected"] == "stale_backlog"
    assert [x["visitors"] for x in t["rows"]] == [40, 72, 88, 80]           # traffic itself is untouched


def test_workshop_clock_and_sql_guard(fake_backend):
    from datetime import datetime

    from agents.cymbal_store_ops.tools.domain_tools import workshop_clock
    assert datetime.fromisoformat(workshop_clock()["rows"][0]["now"]) == datetime.fromisoformat(F.FIXTURE_NOW_ISO)
    r = fake_backend.execute_sql("DELETE FROM fake.cymbal_beauty_fake.products")
    assert r["status"] == "ERROR" and "SELECT" in r["error_details"]
    assert {t["table_id"] for t in fake_backend.list_table_ids()["rows"]} == set(F.EXPECTED_ROW_COUNTS)


def test_fake_backend_satisfies_the_contract(fake_backend):
    from agents.cymbal_store_ops.tools.data_backend import DataBackend
    assert isinstance(fake_backend, DataBackend)
    assert datetime.now(UTC) > NOW - timedelta(days=365)     # sanity: the frozen clock is a real, aware timestamp


def test_writes_ask_for_confirmation_that_names_the_task(fake_backend):
    from agents.cymbal_store_ops.tools.domain_tools import (
        create_store_task,
        delegate_task,
        identify_demo_user,
    )
    ctx = FakeToolContext()
    identify_demo_user(F.HERO_MANAGER_ID, ctx)
    pending = create_store_task("backroom_check", "Move the backroom units to the shelf.", F.HERO_PRODUCT_ID, F.HERO_ASSOCIATE_ID, tool_context=ctx)
    assert pending["status"] == "PENDING_CONFIRMATION"
    hint = ctx.confirmation_requests[-1]["hint"]
    assert "backroom_check" in hint and F.HERO_PRODUCT_ID in hint and F.HERO_ASSOCIATE_ID in hint and F.HERO_STORE_ID in hint
    assert not any(c[0] == "create_store_task" for c in fake_backend.calls)            # nothing written yet
    rejected = FakeToolContext(dict(ctx.state), confirmed=False)
    r = create_store_task("backroom_check", "Move the backroom units to the shelf.", F.HERO_PRODUCT_ID, F.HERO_ASSOCIATE_ID, tool_context=rejected)
    assert r["status"] == "ERROR" and r["code"] == "rejected"
    assert not any(c[0] == "create_store_task" for c in fake_backend.calls)
    assert delegate_task("T-00001", F.HERO_ASSOCIATE_ID, ctx)["status"] == "PENDING_CONFIRMATION"
    assert "Delegate task T-00001" in ctx.confirmation_requests[-1]["hint"]


def test_assignee_is_resolved_by_name_and_never_guessed(fake_backend, manager):
    from agents.cymbal_store_ops.tools.domain_tools import create_store_task
    by_name = create_store_task("backroom_check", "Move the backroom units to the shelf.", F.HERO_PRODUCT_ID,
                                F.HERO_ASSOCIATE_FIRST_NAME, tool_context=manager)
    assert by_name["status"] == "SUCCESS" and by_name["rows"][0]["assignee_id"] == F.HERO_ASSOCIATE_ID
    unknown = create_store_task("replenish", "x", "", "Zelda", tool_context=FakeToolContext(dict(manager.state), confirmed=True))
    assert unknown["code"] == "not_found" and F.HERO_ASSOCIATE_ID in unknown["error_details"]   # lists who works here
    dm = create_store_task("replenish", "x", "", F.HERO_DISTRICT_MANAGER_ID, tool_context=FakeToolContext(dict(manager.state), confirmed=True))
    assert dm["code"] == "invalid_assignee"


def test_unknown_assignee_or_product_fails_before_any_confirmation(fake_backend):
    from agents.cymbal_store_ops.tools.domain_tools import create_store_task, identify_demo_user
    ctx = FakeToolContext()
    identify_demo_user(F.HERO_MANAGER_ID, ctx)
    assert create_store_task("replenish", "x", "", "Nobody", tool_context=ctx)["code"] == "not_found"
    assert create_store_task("replenish", "x", "P-9999", "", tool_context=ctx)["code"] == "not_found"
    assert ctx.confirmation_requests == []     # nothing to approve when the request cannot be carried out


def test_write_budget_stops_a_looping_agent(fake_backend, manager):
    from agents.cymbal_store_ops.tools.domain_tools import WRITES_PER_REQUEST, create_store_task
    notes = [f"note {i}" for i in range(WRITES_PER_REQUEST + 1)]
    results = [create_store_task("cycle_count", n, F.HERO_PRODUCT_ID, "", tool_context=manager) for n in notes]
    assert all(r["status"] == "SUCCESS" for r in results[:WRITES_PER_REQUEST])
    assert results[-1]["code"] == "write_budget"


def test_product_filters_refuse_a_name_instead_of_an_id(fake_backend, manager):
    """A name in product_id silently matched nothing live (loss_prevention passed 'Lumière Hydra Cream')."""
    from agents.cymbal_store_ops.tools import domain_tools as d
    for tool in (d.get_bopis_demand, d.get_replenishment_status, d.get_shrink_signals, d.get_sales_pattern, d.get_task_history):
        r = tool(product_id="Lumière Hydra Cream", tool_context=manager)
        assert r["status"] == "ERROR" and r.get("code") == "invalid_argument", tool.__name__
        assert tool(product_id="P-0101", tool_context=manager)["status"] == "SUCCESS", tool.__name__
    # The task agent has no catalog lookup, so its two tools resolve a name themselves (one match, or they ask).
    assert d.get_task_status(product_id="Lumière Hydra Cream", tool_context=manager)["status"] == "SUCCESS"
    assert d.get_task_status(product_id="cream", tool_context=manager)["code"] == "ambiguous"


def test_coaching_signals_resolve_a_first_name_at_the_store(fake_backend, manager):
    from agents.cymbal_store_ops.tools.domain_tools import get_coaching_signals
    by_name = get_coaching_signals("Noor", tool_context=manager)
    assert by_name["status"] == "SUCCESS" and by_name["associate"]["associate_id"] == F.COACHING_ASSOCIATE_ID
    unknown = get_coaching_signals("Zed", tool_context=manager)
    assert unknown["code"] == "not_found" and "people here" in unknown["error_details"]


def test_product_names_match_without_accents(fake_backend, manager):
    from agents.cymbal_store_ops.tools.domain_tools import check_store_stock, search_products
    typed = check_store_stock("Lumiere Hydra Cream", tool_context=manager)      # a handheld has no "è"
    assert typed["status"] == "SUCCESS" and typed["rows"][0]["product_id"] == F.HERO_PRODUCT_ID
    assert any(r["product_id"] == F.HERO_PRODUCT_ID for r in search_products("lumiere hydra")["rows"])


def test_a_task_can_name_the_product_the_way_the_manager_did(fake_backend, manager):
    """Typed in the dev UI on 2026-09-17: "Create a backroom check task for Lumière Hydra Cream" reached the tool with
    the name as product_id, the tool answered not_found, and no confirmation ever appeared."""
    from agents.cymbal_store_ops.tools.domain_tools import create_store_task
    by_name = create_store_task("backroom_check", "Move the backroom units to the shelf.", F.HERO_PRODUCT_NAME, "Priya", tool_context=manager.new_request())
    assert by_name["status"] == "SUCCESS" and by_name["rows"][0]["product_id"] == F.HERO_PRODUCT_ID
    no_accent = create_store_task("replenish", "Reorder.", "lumiere hydra cream", "", tool_context=manager.new_request())
    assert no_accent["status"] == "SUCCESS" and no_accent["rows"][0]["product_id"] == F.HERO_PRODUCT_ID


def test_a_vague_or_unknown_product_name_is_a_question_not_a_guess(fake_backend):
    from agents.cymbal_store_ops.tools.domain_tools import create_store_task, identify_demo_user
    ctx = FakeToolContext()
    identify_demo_user(F.HERO_MANAGER_ID, ctx)
    vague = create_store_task("replenish", "x", "cream", "", tool_context=ctx)
    assert vague["code"] == "ambiguous" and "Ask the manager which one" in vague["error_details"] and "P-" in vague["error_details"]
    assert create_store_task("replenish", "x", "unobtainium serum", "", tool_context=ctx)["code"] == "not_found"
    assert ctx.confirmation_requests == []


def test_a_task_list_names_the_assignee_and_says_what_is_overdue(fake_backend, manager):
    """Seen in the developer UI on 2026-09-17: "due 04:00 … due 06:00" read out at a 09:00 clock with no word about
    lateness, and assignees as bare ids."""
    from agents.cymbal_store_ops.tools.domain_tools import create_store_task, get_task_status
    rows = get_task_status(tool_context=manager)["rows"]
    assert rows and all("overdue" in r for r in rows)
    late = [r for r in rows if r["overdue"]]
    assert late and all(r["overdue_by_hours"] > 0 for r in late)
    assert all(r["assignee_name"] for r in rows if r.get("assignee_id"))
    create_store_task("backroom_check", "Check the backroom.", F.HERO_PRODUCT_ID, "Priya", tool_context=manager.new_request())
    mine = [r for r in get_task_status(product_id=F.HERO_PRODUCT_ID, tool_context=manager)["rows"]][0]
    assert mine["assignee_name"] == "Priya" and mine["overdue"] is False      # due four hours from the store's clock
