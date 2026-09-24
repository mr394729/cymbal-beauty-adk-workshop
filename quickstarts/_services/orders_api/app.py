"""A tiny mock order management API (FastAPI) for buy-online-pick-up-in-store (BOPIS) orders, used by quickstart 04.

    uv run uvicorn quickstarts._services.orders_api.app:app --port 8010

Every request needs the header X-API-Key: <ORDERS_API_KEY> (default "demo-key"). The OpenAPI document the agent
consumes is checked into quickstarts/04-external-api-agent/openapi.yaml. The orders mirror the workshop data at
store S-014 on the frozen clock (Saturday 2026-10-03 09:00, America/Chicago): three pending orders for Lumière Hydra
Cream promised this morning, and a ready order whose five-day hold ends this afternoon (SOP 06 in quickstart 02).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from fastapi import FastAPI, Header, HTTPException, Query

app = FastAPI(title="Cymbal Beauty Order Management API", version="1.0.0")
HOLD_DAYS = 5
STORE = {"store_id": "S-014", "store_name": "Cymbal Beauty Naperville"}


def _order(order_id: str, status: str, items: list[tuple[str, str, int]], promised_at: str, ready_at: str | None = None) -> dict:
    hold_until = (datetime.fromisoformat(ready_at) + timedelta(days=HOLD_DAYS)).isoformat() if ready_at else None
    return {"order_id": order_id, **STORE, "status": status, "promised_at": promised_at, "ready_at": ready_at,
            "hold_until": hold_until, "items": [{"product_id": p, "name": n, "qty": q} for p, n, q in items]}


ORDERS = {o["order_id"]: o for o in (
    _order("BO-000651", "pending", [("P-0101", "Lumière Hydra Cream", 1)], "2026-10-03T09:30:00-05:00"),
    _order("BO-000652", "pending", [("P-0101", "Lumière Hydra Cream", 2)], "2026-10-03T09:45:00-05:00"),
    _order("BO-000653", "pending", [("P-0101", "Lumière Hydra Cream", 1)], "2026-10-03T10:00:00-05:00"),
    _order("BO-000654", "pending", [("P-0360", "Velvet Bath Soak", 1)], "2026-10-03T10:15:00-05:00"),
    _order("BO-000661", "ready", [("P-0318", "Renew Body Lotion", 1)], "2026-10-02T15:30:00-05:00", "2026-10-02T14:10:00-05:00"),
    _order("BO-000664", "ready", [("P-0333", "Glow Body Wash", 1)], "2026-09-28T14:00:00-05:00", "2026-09-28T15:00:00-05:00"),
    _order("BO-000640", "collected", [("P-0050", "Velvet Moisturizer", 2)], "2026-10-01T12:00:00-05:00", "2026-10-01T10:40:00-05:00"),
)}
STATUSES = ("pending", "picked", "ready", "collected", "cancelled")


def check_key(x_api_key: str | None) -> None:
    if x_api_key != os.environ.get("ORDERS_API_KEY", "demo-key"):
        raise HTTPException(status_code=401, detail="invalid API key")


@app.get("/orders/{order_id}", summary="Get one BOPIS order by id")
def get_order(order_id: str, x_api_key: str | None = Header(default=None)) -> dict:
    check_key(x_api_key)
    if order_id not in ORDERS:
        raise HTTPException(status_code=404, detail=f"order {order_id} not found")
    return ORDERS[order_id]


@app.get("/orders", summary="List a store's BOPIS orders, optionally by status")
def list_orders(store_id: str, status: str | None = Query(default=None),
                x_api_key: str | None = Header(default=None)) -> list[dict]:
    check_key(x_api_key)
    if status is not None and status not in STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {STATUSES}")
    rows = [o for o in ORDERS.values() if o["store_id"] == store_id and (status is None or o["status"] == status)]
    return sorted(rows, key=lambda o: o["promised_at"])
