"""Unit tests: shape of the agent and behaviour of its one tool, with the in-memory backend."""
from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.apps import App


def test_app_exports_and_shape(quickstart):
    assert isinstance(quickstart.app, App) and quickstart.app.name == "hello_tool_agent"
    assert isinstance(quickstart.root_agent, LlmAgent)
    assert [t.__name__ for t in quickstart.root_agent.tools] == ["check_store_stock"]
    assert quickstart.root_agent.sub_agents == []


def test_factory_builds_fresh_agents(quickstart):
    a, b = quickstart.make_root_agent(), quickstart.make_root_agent()
    assert a is not b and a.name == b.name == "hello_tool_agent"


def test_tool_answers_from_the_backend(quickstart, fake_backend):
    tool = quickstart.root_agent.tools[0]
    result = tool("Lumière Hydra Cream", "Naperville")
    assert result["status"] == "SUCCESS"
    row = next(r for r in result["rows"] if r["product_id"] == "P-0101")
    assert row["store_name"] == "Cymbal Beauty Naperville" and row["on_hand"] == 7
    assert fake_backend.calls[-1][0] == "check_store_stock"


def test_tool_error_envelope_for_unknown_city(quickstart, fake_backend):
    result = quickstart.root_agent.tools[0]("Hydra Cream", "Atlantis")
    assert result["status"] == "ERROR" and "Atlantis" in result["error_details"]
