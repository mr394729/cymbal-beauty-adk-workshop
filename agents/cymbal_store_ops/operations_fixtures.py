"""Deterministic source-system snapshots for Cymbal store workflows.

These records define fictional operational systems and targets. They are loaded into BigQuery alongside
store data; the in-memory backend uses the same generator. They do not describe a customer's interfaces.
"""
import json

from agents.cymbal_store_ops.fixtures import FIXTURE_NOW_ISO


def operations_snapshots() -> list[dict]:
    records = []

    def add(system, subject, payload, source):
        records.append(dict(store_id="S-014", system=system, subject_id=subject,
                            captured_at=FIXTURE_NOW_ISO, source=source,
                            payload=json.dumps(payload, ensure_ascii=False)))

    for sku, location, shelf in [("P-0101", "Skincare backstock · bay B2", "Skincare · fixture SK-04"),
                                  ("P-0548", "Makeup backstock · bay M1", "Makeup · fixture MK-02"),
                                  ("P-0420", "Fragrance secure stock · bay F1", "Fragrance · locked case FR-01")]:
        add("stock_location", sku, {"backstock_location": location, "shelf_location": shelf,
            "location_verified_at": "2026-10-03T08:45:00-05:00", "record_version": 1,
            "handling": "Scan the exact product and record the quantity moved; report a mismatch if it cannot be located."}, "inventory-location-service")
    # These reservations reference the existing generated order IDs and quantities. On-hand is gross
    # saleable stock, including reserved units; demand and reservations must never both be subtracted.
    for sku, shelf_qty, backroom_qty, reservations in [
        ("P-0101", 0, 7, [
            {"reservation_id": "RS-014-101-1", "order_id": "BO-000651", "qty": 1, "status": "active"},
            {"reservation_id": "RS-014-101-2", "order_id": "BO-000652", "qty": 2, "status": "active"},
            {"reservation_id": "RS-014-101-3", "order_id": "BO-000653", "qty": 1, "status": "active"}]),
        ("P-0548", 0, 3, []), ("P-0420", 2, 3, []),
    ]:
        add("inventory_allocation", sku, {
            "quantity_basis": "gross_saleable_including_reservations",
            "reservations_complete": True, "reservations": reservations,
            "observed_at": "2026-10-03T08:45:00-05:00",
            "observation_method": "barcode_location_count",
            "freshness_minutes": 45,
            "observed_on_hand": shelf_qty + backroom_qty,
            "observed_on_shelf_qty": shelf_qty, "observed_backroom_qty": backroom_qty,
            "movement_evidence": [{"record_id": f"COUNT-014-{sku}-0845", "type": "count_confirmation",
                                   "observed_at": "2026-10-03T08:45:00-05:00", "quantity_delta": 0,
                                   "saleable_balance": shelf_qty + backroom_qty}],
            "last_failed_pick": None,
        }, "inventory-reservations-and-counts")
    add("coverage", "store", {
        "requirements": [
            {"zone": "cash_wrap", "minimum": 1, "start": "09:00", "end": "11:00"},
            {"zone": "guest_support", "minimum": 1, "start": "09:00", "end": "11:00"}],
        "protected_assignments": [{"associate_id": "A-1002", "zone": "cash_wrap", "until": "11:00"},
                                  {"associate_id": "A-1005", "zone": "guest_support", "until": "10:00"}],
        "breaks": [{"associate_id": "A-1004", "start": "10:30", "end": "10:45"}],
        "planning_estimates": {"bopis_order_minutes": 6, "replenish_sku_minutes": 8},
        "estimate_basis": "Planning estimates, not individual performance targets; exceptions add time.",
        "budget": {"scheduled_hours_today": 46, "budget_hours_today": 48},
        "effective_date": "2026-10-03"}, "workforce-management")
    add("directives", "store", {"directives": [
        {"id": "MD-014-01", "title": "Skincare hydration display", "effective_date": "2026-10-03",
         "due_time": "10:00", "product_id": "P-0101", "fixture": "SK-04", "estimated_minutes": 12,
         "status": "waiting_for_stock", "dependency": "Replenish Lumière Hydra Cream after pickup allocation", "version": 2},
        {"id": "MD-014-02", "title": "Fragrance price-label check", "effective_date": "2026-10-03",
         "due_time": "12:00", "fixture": "FR-01", "estimated_minutes": 8, "status": "ready", "version": 1}]}, "merchandising-task-dashboard")
    add("loss_controls", "P-0420", {"checks": [
        {"id": "LC-014-01", "check": "Locked-case latch", "observed_at": "2026-10-02T17:10:00-05:00",
         "result": "Latch does not consistently catch", "follow_up_task_type": "investigation"},
        {"id": "LC-014-02", "check": "Tester and sellable-stock separation", "observed_at": "2026-10-02T17:15:00-05:00",
         "result": "Tester clearly labelled; no mismatch observed"}],
        "recommended_next_check": "Arrange a latch repair check and reconcile recent recorded loss events against inventory movements.",
        "causation": "The latch finding is a control issue; it does not establish the cause of any loss event."}, "asset-protection-checks")
    add("loss_reconciliation", "P-0420", {
        "window_days": 14,
        "records": [
            {"event_id": "SE-01481", "qty": 1, "value_usd": 95, "finding": "No linked explanation recorded"},
            {"event_id": "SE-01482", "qty": 2, "value_usd": 190, "finding": "No linked explanation recorded"},
            {"event_id": "SE-01483", "qty": 1, "value_usd": 95, "finding": "Damage disposition recorded",
             "linked_record_id": "DMG-014-0420-0928", "linked_record_is_additional_loss": False},
            {"event_id": "SE-01484", "qty": 1, "value_usd": 95, "finding": "Return disposition needs review",
             "linked_record_id": "RET-014-0420-0926", "linked_record_is_additional_loss": False},
            {"event_id": "SE-01485", "qty": 1, "value_usd": 95, "finding": "No linked explanation recorded"},
            {"event_id": "SE-01486", "qty": 1, "value_usd": 95, "finding": "Count adjustment; cause unresolved",
             "linked_record_id": "ADJ-014-0420-0921", "linked_record_is_additional_loss": False}],
        "event_count": 6, "units": 7, "recorded_value_usd": 665,
        "accounting_note": "Linked disposition records describe the existing events; do not add their quantities again.",
        "causation": "Neither an unexplained event nor a control finding identifies a person or establishes theft."
    }, "loss-and-disposition-ledger")
    for aid, completed, ontime, median, searches, interruptions in [
        ("A-1007", 23, 12, 11, 7, 4), ("A-1004", 26, 24, 6.5, 1, 1), ("A-1000", 25, 22, 7, 2, 1)]:
        add("picking_activity", aid, {
            "date": "2026-10-02", "picks_completed": completed, "picks_within_target": ontime,
            "target_minutes": 8, "median_pick_minutes": median, "stock_search_delays": searches,
            "floor_interruptions": interruptions,
            "metric_definition": "One pick is a completed order line; within-target means scan completion within 8 minutes of starting that line.",
            "categories_can_overlap": True,
            "recorded_observations": (["Seven picks carried a stock-location search flag.",
                                        "Four picks were interrupted by guest support."] if aid == "A-1007" else [])}, "fulfillment-activity")
        add("learning", aid, {"completed": ["BOPIS fundamentals"],
            "available": [
                {"id": "LEARN-LOC-01", "title": "Find stock across selling and backstock locations", "minutes": 8,
                 "skill": "stock_location", "activity": "Use location history on one live pick, then compare the scan location."},
                {"id": "LEARN-STAGE-01", "title": "Stage and verify a pickup order", "minutes": 6,
                 "skill": "bopis", "activity": "Check product, quantity and staging location against the order."}],
            "follow_up": "Review the next five completed picks and any stock-search or interruption flags."}, "learning-management")
    return records
