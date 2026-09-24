"""The toolset launches the workshop's MCP server, the server serves the store operations tools unchanged, and the
store scope is enforced on the agent before a call leaves the process. Nothing is spawned; no model."""
from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
from pathlib import Path

import pytest
from google.adk.tools.mcp_tool import McpTool
from mcp import types as mcp_types

from agents.cymbal_store_ops.callbacks import enforce_store_scope_before_tool
from agents.cymbal_store_ops.tools import domain_tools

MANAGER = {"user:user_id": "U-M014", "user:store_id": "S-014", "user:role": "store_manager"}
DISTRICT_MANAGER = {"user:user_id": "A-1001", "user:store_id": "S-014", "user:role": "district_manager"}
SERVED = ("get_osa_exceptions", "check_store_stock")


class Ctx:
    def __init__(self, state: dict) -> None:
        self.state = state


class LocalTool:
    def __init__(self, name: str) -> None:
        self.name = name


def mcp_tool(name: str) -> McpTool:
    return McpTool(mcp_tool=mcp_types.Tool(name=name, inputSchema={"type": "object"}), mcp_session_manager=None)


@pytest.fixture
def server(quickstart):
    spec = importlib.util.spec_from_file_location("cymbal_mcp_server", quickstart.SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def call(server, name: str, args: dict) -> dict:
    """One tools/call through FastMCP, decoded from the JSON text content the client receives."""
    content = asyncio.run(server.mcp.call_tool(name, args))
    return json.loads(content[0].text)


def before_tool(agent, tool, args: dict, state: dict) -> dict | None:
    """The agent's before_tool_callbacks in order, stopping at the first answer (what ADK does)."""
    for callback in agent.before_tool_callback:
        answer = callback(tool, args, Ctx(state))
        if answer is not None:
            return answer
    return None


def test_toolset_points_at_the_custom_server(quickstart):
    toolsets = [t for t in quickstart.root_agent.tools if isinstance(t, quickstart.StdioServerToolset)]
    assert len(toolsets) == 1 and quickstart.server_path().exists()
    params = quickstart.server_params()
    assert params.args[0].endswith("quickstarts/08-mcp-tools-agent/cymbal_mcp_server.py")
    assert set(params.env) <= set(quickstart.SERVER_ENV) | {"PYTHONPATH"} and params.env["WORKSHOP_NAMESPACE"] == "unit"
    assert (Path(params.env["PYTHONPATH"]) / "agents").is_dir()
def test_scope_guard_runs_before_the_stamp(quickstart):
    assert quickstart.root_agent.before_tool_callback == [enforce_store_scope_before_tool, quickstart.stamp_signed_in_store]


def test_server_serves_the_domain_tools_with_their_signatures(server):
    tools = asyncio.run(server.mcp.list_tools())
    assert [t.name for t in tools] == list(SERVED)
    for t in tools:
        domain = getattr(domain_tools, t.name)
        params = {n: p for n, p in inspect.signature(domain).parameters.items() if n != "tool_context"}
        assert list(t.inputSchema["properties"]) == list(params)
        for name, p in params.items():
            assert t.inputSchema["properties"][name].get("default", inspect.Parameter.empty) == p.default
        assert t.description == inspect.getdoc(domain)
        assert t.annotations.readOnlyHint is True


def test_server_answers_exactly_like_the_domain_tool(server, fake_backend):
    stock = call(server, "check_store_stock", {"product_name": "Lumière Hydra Cream", "store_id": "S-014"})
    assert stock == domain_tools.check_store_stock(product_name="Lumière Hydra Cream", store_id="S-014")
    row = stock["rows"][0]
    assert (row["product_id"], row["on_hand"], row["on_shelf_qty"], row["backroom_qty"]) == ("P-0101", 7, 0, 7)
    assert row["recommendation"] == "backroom_check"
    osa = call(server, "get_osa_exceptions", {"limit": 3, "store_id": "S-014"})
    assert osa == domain_tools.get_osa_exceptions(limit=3, store_id="S-014")
    assert osa["rows"][0]["product_id"] == "P-0101"


def test_server_refuses_a_call_without_a_well_formed_store(server, fake_backend):
    missing = call(server, "get_osa_exceptions", {"limit": 3})
    assert missing["status"] == "ERROR" and "stamp_signed_in_store" in missing["error_details"]
    malformed = call(server, "check_store_stock", {"product_name": "Hydra Cream", "store_id": "S-014' OR TRUE"})
    assert malformed["status"] == "ERROR" and malformed["code"] == "invalid_argument"
    by_city = call(server, "check_store_stock", {"product_name": "Lumière Hydra Cream", "city": "Naperville"})
    assert by_city["status"] == "SUCCESS" and {r["store_id"] for r in by_city["rows"]} == {"S-014"}


@pytest.mark.parametrize("state, args, refused, sent_store", [
    (MANAGER, {}, False, "S-014"),                                  # the signed-in store is stamped in
    (MANAGER, {"store_id": "S-014"}, False, "S-014"),
    (MANAGER, {"store_id": "S-020"}, True, "S-020"),                # another store: refused, nothing sent
    (MANAGER, {"city": "Naperville"}, True, None),
    (DISTRICT_MANAGER, {"store_id": "S-020"}, False, "S-020"),      # a district manager may name another store
    ({}, {}, True, None),                                           # nobody signed in
], ids=["stamped", "own-store", "other-store", "city", "district-manager", "signed-out"])
def test_store_scope_before_the_call_leaves(quickstart, state, args, refused, sent_store):
    args = dict(args)
    answer = before_tool(quickstart.root_agent, mcp_tool("get_osa_exceptions"), args, dict(state))
    assert (answer is not None) == refused
    if refused:
        assert answer["status"] == "ERROR"
    assert args.get("store_id") == sent_store


def test_local_tools_are_not_stamped(quickstart):
    args = {"user_id": "U-M014"}
    assert before_tool(quickstart.root_agent, LocalTool("identify_demo_user"), args, {}) is None
    assert args == {"user_id": "U-M014"}


def test_server_is_resolved_where_it_runs(quickstart):
    """Nothing about the spawning machine is fixed at construction: no McpToolset exists until the first request."""
    import sys

    import cloudpickle

    toolset = next(t for t in quickstart.root_agent.tools if isinstance(t, quickstart.StdioServerToolset))
    assert toolset._toolset is None
    assert quickstart.server_params().command == sys.executable
    assert sys.executable.encode() not in cloudpickle.dumps(quickstart.root_agent)
