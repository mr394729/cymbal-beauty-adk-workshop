"""Observed pickup deadlines from the current scoped source; no generated balances."""

from __future__ import annotations

import json

from agents.cymbal_store_ops.tools.data_backend import NOW, make_backend


def observed_event(state: dict) -> dict:
    store_id = state.get("user:store_id")
    if not store_id or state.get("user:role") != "store_manager":
        raise PermissionError("A signed manager store is required")
    result = make_backend().get_bopis_demand(store_id=store_id, product_id=None, hours=2)
    if result.get("status") != "SUCCESS":
        raise RuntimeError(result.get("error_details", "Pickup source read failed"))
    rows = result.get("rows", [])
    return {
        "type": "pickup_deadline",
        "store_id": store_id,
        "as_of": NOW.isoformat(),
        "source": "bopis_orders",
        "window_hours": 2,
        "pending_order_count": result.get("pending_count"),
        "records_complete": result.get("pending_count") == len(rows),
        "orders": [
            {k: row.get(k) for k in ("order_id", "product_id", "qty", "promised_at", "status")}
            for row in rows
        ],
    }


def analysis_message(event: dict) -> str:
    return (
        "Review this recorded pickup-deadline observation for my store. Check the current operational evidence "
        "needed to explain the impact and recommend the next useful decisions. Keep the alert concise. "
        "This is an analysis request only; do not create, assign or change records. The observation is a "
        "source snapshot at its stated as_of time, not a claim that a new order or stock change just occurred.\n"
        + json.dumps(event, sort_keys=True, ensure_ascii=False)
    )
