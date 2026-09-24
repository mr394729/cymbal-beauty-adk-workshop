"""Validation, idempotency and confirmation wiring of the incident intake tools, with no model."""
from __future__ import annotations

from google.adk.tools import FunctionTool


class FakeToolContext:
    def __init__(self, state: dict | None = None) -> None:
        self.state: dict = dict(state or {})


SIGNED_IN = {"user:store_id": "S-014", "user:user_id": "A-1004", "user:role": "associate"}
GOOD = dict(product_id="P-0101", quantity=2, event_type="damage", location="skincare aisle",
            note="Two jars cracked when a tote fell during restock.")


def test_find_product_resolves_the_catalog(quickstart, fake_backend):
    result = quickstart.find_product("Lumière Hydra Cream")
    assert result["status"] == "SUCCESS"
    assert result["rows"][0]["product_id"] == "P-0101" and set(result["rows"][0]) == {"product_id", "name", "brand", "category", "locked_case"}
    assert quickstart.find_product("no such thing xyz")["status"] == "ERROR"


def test_submit_validates_every_field(quickstart):
    ctx = FakeToolContext(SIGNED_IN)
    for bad in ({"product_id": "Hydra Cream"}, {"quantity": 0}, {"event_type": "theft"}, {"location": " "},
                {"note": "call Priya on 312-555-0100"}):
        assert quickstart.submit_incident_report(**{**GOOD, **bad}, tool_context=ctx)["status"] == "ERROR", bad


def test_submit_needs_a_signed_in_store(quickstart):
    result = quickstart.submit_incident_report(**GOOD, tool_context=FakeToolContext())
    assert result["status"] == "ERROR" and "identify_demo_user" in result["error_details"]


def test_submit_is_idempotent_and_writes_nothing(quickstart):
    ctx = FakeToolContext(SIGNED_IN)
    first = quickstart.submit_incident_report(**GOOD, tool_context=ctx)
    second = quickstart.submit_incident_report(**GOOD, tool_context=ctx)
    assert first["status"] == "SUCCESS" and first["written"] is False
    assert first["rows"][0]["incident_id"] == second["rows"][0]["incident_id"]
    assert first["rows"][0]["store_id"] == "S-014" and first["rows"][0]["reported_by"] == "A-1004"


def test_submit_tool_requires_confirmation(quickstart):
    submit = next(t for t in quickstart.root_agent.tools if getattr(t, "name", "") == "submit_incident_report")
    assert isinstance(submit, FunctionTool) and submit._require_confirmation is True
    names = [getattr(t, "name", getattr(t, "__name__", "")) for t in quickstart.root_agent.tools]
    assert names == ["identify_demo_user", "find_product", "get_user_choice", "submit_incident_report"]
