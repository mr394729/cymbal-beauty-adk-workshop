"""The OpenAPI document becomes tools; the mock order management API enforces the key. No model, no network."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

KEY = {"X-API-Key": "demo-key"}


def test_openapi_toolset_exposes_the_two_operations(quickstart):
    toolset = quickstart.root_agent.tools[0]
    names = sorted(t.name for t in asyncio.run(toolset.get_tools()))
    assert names == ["get_order", "list_orders"]


def test_mock_orders_api_requires_the_key():
    from quickstarts._services.orders_api.app import app

    client = TestClient(app)
    assert client.get("/orders/BO-000651").status_code == 401
    ok = client.get("/orders/BO-000651", headers=KEY)
    assert ok.status_code == 200 and ok.json()["status"] == "pending" and ok.json()["items"][0]["product_id"] == "P-0101"
    assert client.get("/orders/BO-1", headers=KEY).status_code == 404


def test_ready_orders_carry_a_five_day_hold():
    from quickstarts._services.orders_api.app import app

    ready = TestClient(app).get("/orders", params={"store_id": "S-014", "status": "ready"}, headers=KEY).json()
    assert [o["order_id"] for o in ready] == ["BO-000664", "BO-000661"]
    assert ready[0]["hold_until"] == "2026-10-03T15:00:00-05:00"
    assert TestClient(app).get("/orders", params={"store_id": "S-014", "status": "lost"}, headers=KEY).status_code == 422


def test_missing_key_is_loud(quickstart, monkeypatch):
    monkeypatch.delenv("ORDERS_API_KEY")
    with pytest.raises(RuntimeError, match="ORDERS_API_KEY"):
        quickstart.orders_toolset()
