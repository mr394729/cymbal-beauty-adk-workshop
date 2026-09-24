"""Inventory decisions change when reservations, evidence freshness or pick outcomes change."""
import json
import threading
from functools import wraps

import pytest

from agents.cymbal_store_ops.tools.inventory_context import get_inventory_context
from tests.conftest import FakeToolContext


def context(store="S-014"):
    return FakeToolContext({"user:store_id": store, "user:user_id": "A-1004", "user:role": "associate"})


def change_allocation(backend, **changes):
    record = next(r for r in backend.operations if r["system"] == "inventory_allocation" and r["subject_id"] == "P-0101")
    payload = json.loads(record["payload"])
    payload.update(changes)
    record["payload"] = json.dumps(payload)


@pytest.mark.asyncio
async def test_known_fresh_stock_is_picked_without_recount_and_allocations_are_not_double_subtracted(fake_backend):
    result = await get_inventory_context("Hydra Cream", context())
    assert result["status"] == "SUCCESS"
    row = result["rows"][0]
    decision = row["decision"]
    assert row["availability_flags"] == ["empty_shelf_with_store_stock", "below_reorder_point"]
    assert decision["evidence_gaps"] == []
    assert decision["reservations_known"]
    assert row["allocation"]["source_status"] == "available"
    assert all(value == "available" for value in row["source_availability"].values())
    assert decision["reserved_units"] == decision["pending_demand_units"] == 4
    assert decision["pending_order_count"] == 3
    assert decision["available_to_promise_units"] == decision["shelf_replenishment_units"] == 3
    assert decision["unreserved_pending_units"] == 0
    assert decision["action"] == "pick_reserved_then_replenish"
    assert not decision["physical_check_needed"]
    assert decision["stock_observation_age_minutes"] == 15
    assert decision["inbound_delayed"]
    assert row["location"]["backstock_location"] == "Skincare backstock · bay B2"
    orders = {r["order_id"]: r for r in row["demand"]["rows"]}
    assert all(orders[r["order_id"]]["qty"] == r["qty"] for r in row["allocation"]["reservations"])
    assert row["inbound"][0]["qty"] == 12 and row["inbound"][0]["status"] == "delayed"


@pytest.mark.asyncio
async def test_pending_demand_is_not_misrepresented_as_reserved_stock(fake_backend):
    change_allocation(fake_backend, reservations=[])
    decision = (await get_inventory_context("P-0101", context()))["rows"][0]["decision"]
    assert decision["reserved_units"] == 0
    assert decision["reservations_known"]
    assert decision["observed_reserved_units"] == 0
    assert decision["available_to_promise_units"] == 7
    assert decision["unreserved_pending_units"] == 4
    assert decision["shelf_replenishment_units"] == 3
    assert decision["action"] == "allocate_pending_demand"


@pytest.mark.asyncio
@pytest.mark.parametrize(("change", "reason"), [
    ({"observed_at": "2026-10-03T07:30:00-05:00"}, "stock_observation_stale_or_missing"),
    ({"observed_backroom_qty": 5}, "stock_count_conflict"),
    ({"last_failed_pick": {"order_id": "BO-000651", "reason": "Empty recorded bin"}}, "failed_pick_requires_reconciliation"),
])
async def test_specific_stock_evidence_changes_recommendation(fake_backend, change, reason):
    change_allocation(fake_backend, **change)
    decision = (await get_inventory_context("Hydra Cream", context()))["rows"][0]["decision"]
    assert decision["physical_check_needed"]
    assert reason in decision["evidence_gaps"]
    assert decision["action"] == "resolve_stock_discrepancy"
    assert decision["available_to_promise_units"] is None
    assert decision["shelf_replenishment_units"] is None


@pytest.mark.asyncio
async def test_incomplete_reservations_do_not_produce_false_available_stock(fake_backend):
    change_allocation(fake_backend, reservations_complete=False)
    decision = (await get_inventory_context("Hydra Cream", context()))["rows"][0]["decision"]
    assert decision["available_to_promise_units"] is None
    assert decision["action"] == "resolve_inventory_evidence"
    assert not decision["physical_check_needed"]
    assert decision["reserved_units"] is None
    assert decision["observed_reserved_units"] == 4
    assert decision["unreserved_pending_units"] is None
    assert not decision["reservations_known"]


@pytest.mark.asyncio
async def test_missing_snapshot_is_an_explicit_gap_not_zero_reservations(fake_backend):
    fake_backend.operations = [r for r in fake_backend.operations if r["system"] != "inventory_allocation"]
    row = (await get_inventory_context("Hydra Cream", context()))["rows"][0]
    decision = row["decision"]
    assert decision["evidence_gaps"] == ["allocation_evidence_missing"]
    assert decision["available_to_promise_units"] is None
    assert decision["reserved_units"] is None and decision["unreserved_pending_units"] is None
    assert not decision["reservations_known"]
    assert decision["pending_order_count"] == 3 and decision["pending_demand_units"] == 4
    assert row["stock"]["on_hand"] == 7 and row["stock"]["backroom_qty"] == 7
    assert row["allocation"]["source_status"] == row["source_availability"]["allocation"] == "missing"
    assert row["allocation"]["reservations"] is None
    assert row["source_availability"]["location"] == "available"


@pytest.mark.asyncio
@pytest.mark.parametrize("product_id", ["P-0217", "P-0312"])
async def test_nonhero_stock_without_snapshots_retains_stock_and_distinguishes_zero_demand_from_unknown_reservations(
    fake_backend, product_id,
):
    expected = fake_backend.check_store_stock(product_name=product_id, store_id="S-014")["rows"][0]
    result = await get_inventory_context(product_id, context())
    assert result["status"] == "SUCCESS"
    row = result["rows"][0]
    assert row["stock"] == expected
    assert row["source_availability"]["allocation"] == row["source_availability"]["location"] == "missing"
    assert row["source_availability"]["demand"] == "available"
    assert row["decision"]["pending_order_count"] == row["demand"]["pending_count"]
    assert row["decision"]["pending_demand_units"] == row["demand"]["units_total"]
    for key in ("reserved_units", "observed_reserved_units", "unreserved_pending_units",
                "available_to_promise_units", "shelf_replenishment_units"):
        assert row["decision"][key] is None
    assert row["allocation"]["reservations"] is None
    assert not row["decision"]["physical_check_needed"]


@pytest.mark.asyncio
async def test_completeness_flag_without_reservation_records_cannot_prove_zero(fake_backend):
    change_allocation(fake_backend, reservations=None, reservations_complete=True)
    row = (await get_inventory_context("P-0101", context()))["rows"][0]
    assert not row["decision"]["reservations_known"]
    assert row["decision"]["reserved_units"] is None
    assert row["decision"]["available_to_promise_units"] is None
    assert "reservation_coverage_incomplete" in row["decision"]["evidence_gaps"]


@pytest.mark.asyncio
async def test_source_failure_is_not_silently_treated_as_empty_data(fake_backend, monkeypatch):
    monkeypatch.setattr(fake_backend, "get_replenishment_status", lambda **kwargs: {"status": "ERROR", "error_details": "Feed unavailable"})
    result = await get_inventory_context("Hydra Cream", context())
    assert result["status"] == "ERROR" and result["failed_source"] == "supply"


@pytest.mark.asyncio
async def test_independent_reads_really_overlap(fake_backend, monkeypatch):
    barrier = threading.Barrier(5)

    def synchronized(read):
        @wraps(read)
        def wrapped(*args, **kwargs):
            barrier.wait(timeout=5)
            return read(*args, **kwargs)
        return wrapped

    # get_operations_context runs twice, so these four methods represent five independent reads.
    for name in ("get_bopis_demand", "get_operations_context", "get_replenishment_status", "get_task_status"):
        monkeypatch.setattr(fake_backend, name, synchronized(getattr(fake_backend, name)))
    manager = FakeToolContext({"user:store_id": "S-014", "user:user_id": "U-M014", "user:role": "store_manager"})
    result = await get_inventory_context("Hydra Cream", manager)
    assert result["status"] == "SUCCESS"


@pytest.mark.asyncio
async def test_no_identity_and_ambiguous_products_do_not_fetch_arbitrary_records(fake_backend):
    assert (await get_inventory_context("Hydra Cream"))["status"] == "ERROR"
    assert (await get_inventory_context("", context()))["code"] == "invalid_argument"
    assert (await get_inventory_context("Cream", context()))["code"] == "ambiguous"


def test_reconciliation_snapshot_refers_to_existing_events_without_counting_documents_twice(fake_backend):
    result = fake_backend.get_operations_context(store_id="S-014", system="loss_reconciliation", subject_id="P-0420")
    snapshot = result["rows"][0]["payload"]
    events = {r["event_id"]: r for r in fake_backend.shrink}
    assert len(snapshot["records"]) == snapshot["event_count"] == 6
    assert sum(r["qty"] for r in snapshot["records"]) == snapshot["units"] == 7
    assert sum(r["value_usd"] for r in snapshot["records"]) == snapshot["recorded_value_usd"] == 665
    for row in snapshot["records"]:
        assert events[row["event_id"]]["qty"] == row["qty"]
        assert events[row["event_id"]]["value_usd"] == row["value_usd"]
        if row.get("linked_record_id"):
            assert row["linked_record_is_additional_loss"] is False
