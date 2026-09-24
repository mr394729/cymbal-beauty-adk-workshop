"""A stdio MCP server that exposes two store operations tools over the same DataBackend the agent uses.

    uv run python quickstarts/08-mcp-tools-agent/cymbal_mcp_server.py        # speaks MCP on stdin/stdout

This is the "someone else's MCP server" pattern: the ADK agent (quickstarts/08-mcp-tools-agent) is an MCP client
and never imports this code. The tools are the store manager's own `get_osa_exceptions` and `check_store_stock`
from agents/cymbal_store_ops/tools/domain_tools.py, called as they are: same arguments, same envelope, same OSA rule.

An MCP server has no session, so it cannot know who is signed in. The store travels as the `store_id` argument:
the client agent checks the store scope and fills in the signed-in store before the call leaves the process, and
this server refuses a call without a well-formed one. Never print to stdout here: stdout is the MCP transport.
"""
from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

# The directory that holds the `agents` package: the repo root here, or the deployment root when this file is staged
# next to quickstart 08's agent on Agent Runtime.
ROOT = next(p for p in Path(__file__).resolve().parents if (p / "agents" / "cymbal_store_ops").is_dir())
sys.path.insert(0, str(ROOT))

from agents.cymbal_store_ops.tools import domain_tools  # noqa: E402
from agents.cymbal_store_ops.tools.data_backend import err  # noqa: E402

STORE_ID = re.compile(r"S-\d{3,5}")   # S-014 in the workshop; real store numbers run longer
NO_STORE = ("store_id is required over MCP because the server has no session: the client agent passes the signed-in "
            "store (stamp_signed_in_store in quickstarts/08-mcp-tools-agent/agent.py)")
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

mcp = FastMCP("cymbal-beauty-store-ops")


def bad_store(store_id: str, city: str = "") -> dict | None:
    """The error envelope for a missing or malformed store id; None when the call may go ahead."""
    if store_id and not STORE_ID.fullmatch(store_id):
        return err(f"store_id {store_id!r} is not a store id like S-014", code="invalid_argument")
    if not store_id and not city:
        return err(NO_STORE, code="invalid_argument")
    return None


@mcp.tool(description=inspect.getdoc(domain_tools.get_osa_exceptions), annotations=READ_ONLY)
def get_osa_exceptions(limit: int = 20, store_id: str = "") -> dict:
    return bad_store(store_id) or domain_tools.get_osa_exceptions(limit=limit, store_id=store_id)


@mcp.tool(description=inspect.getdoc(domain_tools.check_store_stock), annotations=READ_ONLY)
def check_store_stock(product_name: str, city: str = "", store_id: str = "") -> dict:
    return bad_store(store_id, city) or domain_tools.check_store_stock(product_name=product_name, city=city,
                                                                      store_id=store_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
