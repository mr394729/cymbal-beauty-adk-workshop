"""Structural guarantees of the built agent tree (no model calls)."""
from __future__ import annotations

import inspect

from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool

SCOPED_PARAMS = {"store_id", "city", "tool_context"}


def _walk(agent, seen=None):
    seen = seen if seen is not None else set()
    if id(agent) in seen:
        return
    seen.add(id(agent))
    yield agent
    for sub in getattr(agent, "sub_agents", None) or []:
        yield from _walk(sub, seen)
    for tool in getattr(agent, "tools", None) or []:
        if isinstance(tool, AgentTool):
            yield from _walk(tool.agent, seen)


def _callbacks(agent) -> list:
    cb = agent.before_tool_callback
    return list(cb) if isinstance(cb, list) else ([cb] if cb else [])


def _store_scoped_functions(agent) -> list[str]:
    names = []
    for tool in agent.tools or []:
        fn = tool if callable(tool) and not hasattr(tool, "run_async") else getattr(tool, "func", None)
        if fn is None:
            continue
        if SCOPED_PARAMS & set(inspect.signature(fn).parameters):
            names.append(fn.__name__)
    return names


def test_every_agent_owning_a_store_scoped_tool_enforces_store_scope():
    from agents.cymbal_store_ops.agent import root_agent
    from agents.cymbal_store_ops.callbacks import enforce_store_scope_before_tool

    missing = []
    checked = 0
    for agent in _walk(root_agent):
        if not isinstance(agent, LlmAgent):
            continue
        scoped = _store_scoped_functions(agent)
        if scoped:
            checked += 1
            if enforce_store_scope_before_tool not in _callbacks(agent):
                missing.append(f"{agent.name}: {scoped}")
    assert checked >= 6, f"expected root, 3 consultants, store_tasks and coaching; saw {checked}"
    assert not missing, f"agents that own store-scoped tools without the store-scope callback: {missing}"


def test_coaching_agent_keeps_the_role_gate():
    from agents.cymbal_store_ops.agent import root_agent
    from agents.cymbal_store_ops.callbacks import enforce_role_before_tool

    coaching = next(a for a in _walk(root_agent) if a.name == "associate_development")
    assert enforce_role_before_tool in _callbacks(coaching)


def test_inventory_agent_can_receive_another_store_for_district_managers():
    """The district-manager exercise asks about S-001: the store id must survive the root -> single_turn hand-off."""
    from agents.cymbal_store_ops.sub_agents.inventory_excellence import OsaQuery

    assert "store_id" in OsaQuery.model_fields


def test_single_turn_consultants_cannot_transfer_control_back_into_the_root():
    """A consultant returns a result; transferring re-enters the root and can duplicate its answer."""
    from agents.cymbal_store_ops.agent import root_agent

    consultants = {agent.name: agent for agent in _walk(root_agent)
                   if isinstance(agent, LlmAgent) and agent.mode == "single_turn"}
    assert set(consultants) == {"inventory_excellence", "associate_orchestration", "loss_prevention"}
    for name, agent in consultants.items():
        assert agent.disallow_transfer_to_parent, f"{name} can re-enter the root during a tool call"
        assert agent.disallow_transfer_to_peers, f"{name} can bypass the coordinator by transferring to a peer"
