from copy import deepcopy
from datetime import UTC, timedelta

import pytest

from agents.cymbal_store_ops.tools.data_backend import NOW
from agents.cymbal_store_ops.tools.pickup_workload import estimate_queue, get_pickup_workload
from tests.conftest import FakeToolContext


@pytest.mark.asyncio
async def test_queue_estimate_does_not_treat_first_promise_as_deadline_for_every_order(fake_backend):
    context = FakeToolContext({"user:user_id": "U-M014", "user:store_id": "S-014", "user:role": "store_manager"})
    result = await get_pickup_workload(tool_context=context)
    assert result["status"] == "SUCCESS", result
    plan = result["rows"][0]
    assert plan["pending_order_count"] == 9
    assert plan["pending_unit_count"] == 13
    assert plan["estimated_minutes"] == 54
    assert plan["estimated_queue_finish"] == (NOW + timedelta(minutes=54)).isoformat()
    assert not plan["whole_queue_can_finish_by_first_promise"]
    assert plan["orders_due_at_first_promise"] < 9
    assert plan["orders_late_in_estimate"] == 0


def test_queue_estimate_flags_deadlines_that_cannot_be_met_and_sorts_due_work():
    orders = [{"order_id": str(i), "product_id": "P-0101", "qty": 1,
               "promised_at": (NOW + timedelta(minutes=i)).isoformat()} for i in (10, 2)]
    plan = estimate_queue(orders, 6)
    assert [row["order_id"] for row in plan["orders"]] == ["2", "10"]
    assert plan["orders_late_in_estimate"] == 2
    assert plan["orders_due_at_first_promise"] == 1


@pytest.mark.asyncio
async def test_unsigned_queue_has_no_backend_access(fake_backend):
    result = await get_pickup_workload(tool_context=FakeToolContext())
    assert result["status"] == "ERROR"


def test_unit_total_uses_quantities_and_changes_with_source_records():
    orders = [{"order_id": str(i), "product_id": "P-any", "qty": qty,
               "promised_at": (NOW + timedelta(minutes=30)).isoformat()}
              for i, qty in enumerate((2, 4, 7))]
    assert estimate_queue(orders, 6)["pending_unit_count"] == 13
    orders[1]["qty"] = 9
    assert estimate_queue(orders, 6)["pending_unit_count"] == 18
    assert estimate_queue([], 6)["pending_unit_count"] == 0


def test_latest_start_respects_tightest_order_prefix_and_actual_start():
    orders = [{"order_id": str(i), "product_id": "P-any", "qty": 1,
               "promised_at": (NOW + timedelta(minutes=due)).isoformat()}
              for i, due in enumerate((20, 22, 60))]
    plan = estimate_queue(orders, 6)
    assert plan["latest_uninterrupted_start"] == (NOW + timedelta(minutes=10)).isoformat()
    assert plan["minimum_schedule_slack_minutes"] == 10
    at_limit = estimate_queue(orders, 6, start=NOW + timedelta(minutes=10))
    assert at_limit["orders_late_in_estimate"] == 0
    too_late = estimate_queue(orders, 6, start=NOW + timedelta(minutes=11))
    assert too_late["orders_late_in_estimate"] == 1
    assert too_late["minimum_schedule_slack_minutes"] == -1
    empty = estimate_queue([], 6)
    assert empty["latest_uninterrupted_start"] is None
    assert empty["minimum_schedule_slack_minutes"] is None


def test_alternative_start_and_finish_preserve_the_tightest_nonfirst_promise():
    orders = [{"order_id": str(i), "product_id": "P-any", "qty": i + 1,
               "promised_at": (NOW + timedelta(minutes=due)).astimezone(UTC).isoformat()}
              for i, due in enumerate((20, 22, 60))]
    original = deepcopy(orders)
    plan = estimate_queue(orders, 6)
    snapshot = plan["schedule_scenarios"]["snapshot_start"]
    latest = plan["schedule_scenarios"]["latest_uninterrupted_start"]
    assert snapshot["start"] == NOW.isoformat()
    assert snapshot["estimated_queue_finish"] == (NOW + timedelta(minutes=18)).isoformat()
    assert latest["start"] == (NOW + timedelta(minutes=10)).isoformat()
    assert latest["estimated_queue_finish"] == (NOW + timedelta(minutes=28)).isoformat()
    assert [row["units"] for row in plan["orders"]] == [1, 2, 3]
    assert [row["promised_by"] for row in plan["orders"]] == [order["promised_at"] for order in orders]
    assert plan["orders"][1]["estimated_finish"] == (NOW + timedelta(minutes=12)).isoformat()
    for scenario in (snapshot, latest):
        assert scenario["start_at_or_after_snapshot"]
        assert scenario["feasible_from_snapshot"]
        assert scenario["orders_late_in_estimate"] == 0
        assert "orders" not in scenario
    assert orders == original


def test_past_latest_start_is_not_presented_as_achievable_from_now():
    orders = [{"order_id": "overdue", "product_id": "P-any", "qty": 2,
               "promised_at": (NOW - timedelta(minutes=5)).isoformat()}]
    scenarios = estimate_queue(orders, 6)["schedule_scenarios"]
    assert scenarios["snapshot_start"]["orders_late_in_estimate"] == 1
    assert not scenarios["snapshot_start"]["feasible_from_snapshot"]
    latest = scenarios["latest_uninterrupted_start"]
    assert latest["start"] == (NOW - timedelta(minutes=11)).isoformat()
    assert latest["estimated_queue_finish"] == orders[0]["promised_at"]
    assert latest["orders_late_in_estimate"] == 0
    assert not latest["start_at_or_after_snapshot"]
    assert not latest["feasible_from_snapshot"]


def test_empty_queue_has_no_latest_start_requirement_or_invented_work():
    plan = estimate_queue([], 6)
    assert plan["schedule_scenarios"]["latest_uninterrupted_start"] is None
    assert plan["schedule_scenarios"]["snapshot_start"] == {
        "start": NOW.isoformat(), "estimated_queue_finish": NOW.isoformat(),
        "orders_late_in_estimate": 0,
        "start_at_or_after_snapshot": True, "feasible_from_snapshot": True,
    }


@pytest.mark.asyncio
async def test_full_fixture_queue_exposes_different_paired_finishes(fake_backend):
    context = FakeToolContext({"user:user_id": "U-M014", "user:store_id": "S-014", "user:role": "store_manager"})
    plan = (await get_pickup_workload(tool_context=context))["rows"][0]
    snapshot = plan["schedule_scenarios"]["snapshot_start"]
    latest = plan["schedule_scenarios"]["latest_uninterrupted_start"]
    assert snapshot["estimated_queue_finish"] == (NOW + timedelta(minutes=54)).isoformat()
    assert latest["start"] == (NOW + timedelta(minutes=24)).isoformat()
    assert latest["estimated_queue_finish"] == (NOW + timedelta(minutes=78)).isoformat()
    assert len(plan["orders"]) == plan["pending_order_count"] == 9
    assert sum(row["units"] for row in plan["orders"]) == plan["pending_unit_count"] == 13
    assert all("orders" not in scenario for scenario in (snapshot, latest))


def test_promise_check_reads_each_order_against_its_own_promise():
    """A queue that finishes after the first promise can still meet every promise; the tool says so in words."""
    from agents.cymbal_store_ops.tools.pickup_workload import estimate_queue

    orders = [{"order_id": "A", "product_id": "P", "qty": 1, "promised_at": "2026-10-03T09:30-05:00"},
              {"order_id": "B", "product_id": "P", "qty": 1, "promised_at": "2026-10-03T11:00-05:00"}]
    met = estimate_queue(orders, 30)
    assert met["whole_queue_can_finish_by_first_promise"] is False
    assert met["promise_check"] == "All 2 orders finish by their own promise times; the first, due 9:30 AM, is ready about 9:30 AM."
    late = estimate_queue(orders, 40)
    assert late["promise_check"].startswith("1 of 2 orders would miss their promise; the first miss is A, due 9:30 AM")
