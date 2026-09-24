"""Operating modes decide tool call versus transfer; factories give fresh trees."""
from __future__ import annotations


def test_modes_wire_the_tree(quickstart):
    root = quickstart.root_agent
    assert [a.name for a in root.sub_agents] == ["coaching_specialist", "stock_lookup"]
    stock = root.sub_agents[1]
    assert stock.mode == "single_turn" and stock.input_schema is quickstart.StockQuery
    assert any(getattr(t, "name", "") == "stock_lookup" for t in root.tools), "single_turn sub-agent is exposed as a tool"


def test_fresh_tree_per_factory_call(quickstart):
    a, b = quickstart.make_root_agent(), quickstart.make_root_agent()
    assert a.sub_agents[0] is not b.sub_agents[0]


def test_coaching_specialist_keeps_the_people_data_guardrails(quickstart):
    from agents.cymbal_store_ops.callbacks import (
        enforce_role_before_tool,
        enforce_store_scope_before_tool,
    )
    coaching = quickstart.root_agent.sub_agents[0]
    assert coaching.before_tool_callback == [enforce_store_scope_before_tool, enforce_role_before_tool]
