"""Quickstart 08 — MCP tools agent.

The agent is an MCP client: `McpToolset` starts the workshop's custom MCP server over stdio and discovers its
tools at runtime (`get_osa_exceptions`, `check_store_stock`); the agent code never imports the server. The same
toolset with `StreamableHTTPConnectionParams` reaches a remote server (MCP Toolbox for Databases, a partner's MCP
endpoint, any server in Agent Registry).

A server has no session, so the signed-in store must travel as an argument. Two `before_tool_callback`s run on
this agent, the one that owns the toolset, before anything leaves the process: the store-scope guard refuses
another store or a city unless the caller is a district manager, then `stamp_signed_in_store` fills an empty
`store_id` with the session's store. The model never has to know or type the store id.
"""
from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message=r".*\[EXPERIMENTAL\].*", module=r"google\.adk.*")

from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.apps import App  # noqa: E402
from google.adk.tools import BaseTool, ToolContext  # noqa: E402
from google.adk.tools.base_toolset import BaseToolset  # noqa: E402
from google.adk.tools.mcp_tool import McpTool, McpToolset, StdioConnectionParams  # noqa: E402
from mcp import StdioServerParameters  # noqa: E402

from agents.cymbal_store_ops.callbacks import enforce_store_scope_before_tool  # noqa: E402
from agents.cymbal_store_ops.config import load_env_config  # noqa: E402
from agents.cymbal_store_ops.models import workshop_model  # noqa: E402
from agents.cymbal_store_ops.tools.domain_tools import (  # noqa: E402
    STATE_STORE_ID,
    identify_demo_user,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
# A stdio server inherits only PATH/HOME-style variables; hand it the workshop settings so it reads the same
# dataset (namespace, environment, fault switch) as this agent. Anything unset here comes from .env.
SERVER_ENV = ("GOOGLE_CLOUD_PROJECT", "WORKSHOP_NAMESPACE", "STORE_OPS_ENV", "STORE_OPS_FAULT", "BQ_LOCATION",
              "GOOGLE_APPLICATION_CREDENTIALS", "CLOUDSDK_CONFIG")
INSTRUCTION = """You help Cymbal Beauty store managers and associates; your store tools arrive over MCP.
Signed-in store: {user:store_id?}, role: {user:role?}. If no one is signed in, ask for the demo id (for example
U-M014) and call identify_demo_user.
- get_osa_exceptions lists the store's on-shelf availability exceptions, worst first, each with a recommendation.
- check_store_stock gives one product's position: on hand, on the shelf, in the backroom, reorder point, pick-up
  eligibility and the recommendation.
Leave store_id empty: the signed-in store is filled in for you. Only a district manager names another store or a
city. Answer in two or three sentences, only from tool results, with the product id and the recommendation; if a
tool returns status ERROR, say what could not be done."""


def server_path() -> Path:
    """The server is packaged beside the client locally and on Agent Runtime."""
    return Path(__file__).with_name("cymbal_mcp_server.py")


def agents_root() -> Path:
    """The directory holding the `agents` package: the repo root, or the deployment root on Agent Runtime."""
    here = Path(__file__).resolve()
    for candidate in [here.parent, *here.parents]:
        if (candidate / "agents" / "cymbal_store_ops").is_dir():
            return candidate
    raise RuntimeError(f"no `agents` package above {here}: the MCP server cannot import the domain tools")


def server_params() -> StdioServerParameters:
    """Interpreter, server file and PYTHONPATH as they are on the machine that spawns the server."""
    env = {k: os.environ[k] for k in SERVER_ENV if os.environ.get(k)}
    env["PYTHONPATH"] = str(agents_root())
    return StdioServerParameters(command=sys.executable, args=[str(server_path())], env=env)


SERVER = server_path()   # where the server is on this machine (tests and the standalone client read it)


class StdioServerToolset(BaseToolset):
    """An McpToolset over the workshop's stdio server, built on first use rather than at construction.

    Agent Runtime pickles the agent on the deploying machine; a McpToolset built there carries that machine's
    interpreter and file paths into the engine, where neither exists (seen live: `python3: can't open file
    '/tmp/.../cymbal_mcp_server.py'`). Resolving them when the first request arrives keeps one agent definition
    correct locally and on the engine."""

    def __init__(self) -> None:
        super().__init__()
        self._toolset: McpToolset | None = None

    def _real(self) -> McpToolset:
        if self._toolset is None:
            self._toolset = McpToolset(connection_params=StdioConnectionParams(server_params=server_params(), timeout=30))
        return self._toolset

    async def get_tools(self, readonly_context=None):
        return await self._real().get_tools(readonly_context)

    async def close(self) -> None:
        if self._toolset is not None:
            await self._toolset.close()


def cymbal_mcp_tools() -> StdioServerToolset:
    return StdioServerToolset()


def stamp_signed_in_store(tool: BaseTool, args: dict, tool_context: ToolContext) -> dict | None:
    """An MCP call without a store_id gets the session's store. Runs after the scope guard, which has already
    refused a session with no store and a store the caller may not see."""
    if isinstance(tool, McpTool) and not args.get("store_id"):
        args["store_id"] = tool_context.state[STATE_STORE_ID]
    return None


def make_root_agent() -> LlmAgent:
    cfg = load_env_config()
    return LlmAgent(
        name="mcp_tools_agent",
        model=workshop_model(cfg),
        description="On-shelf availability exceptions and stock positions for the signed-in store, through tools "
                    "served over the Model Context Protocol.",
        instruction=INSTRUCTION,
        tools=[identify_demo_user, cymbal_mcp_tools()],
        before_tool_callback=[enforce_store_scope_before_tool, stamp_signed_in_store],
    )


def create_app() -> App:
    return App(name="mcp_tools_agent", root_agent=make_root_agent())


app = create_app()
root_agent = app.root_agent
