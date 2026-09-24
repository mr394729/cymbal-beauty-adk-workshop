"""The agent's connection to the MCP server that serves its store reads (see mcp_catalog.py)."""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from urllib.parse import urlsplit

from google.adk.tools.mcp_tool import McpTool, McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

from agents.cymbal_store_ops.mcp_auth import Scope, Settings, sign_scope
from agents.cymbal_store_ops.mcp_catalog import READS

# Everything the server offers: the store reads, schema discovery for other MCP clients, and the report rows that
# deliver_store_report turns into the on-screen table and the full metrics behind the end-of-day PDF (both called
# from code, never offered to the model).
TOOLS = sorted({*READS, "describe_store_data", "read_store_report", "read_end_of_day_report"})


def registry_toolspec(tools: list[dict]) -> dict:
    """The tool list for the Agent Registry entry: names, first description line, argument shapes.

    The registry caps an upload at 10 KB; full descriptions for 31 tools are about 26 KB. Agents still read the
    full descriptions from the server itself when they connect."""
    def strip(schema):
        if isinstance(schema, dict):
            return {key: strip(value) for key, value in schema.items() if key not in ("description", "title", "default")}
        if isinstance(schema, list):
            return [strip(item) for item in schema]
        return schema
    return {"tools": [{"name": tool["name"], "description": (tool.get("description") or "").split("\n")[0][:60],
                       "inputSchema": strip(tool.get("inputSchema", {}))} for tool in tools]}


class IdentityTokenProvider:
    """Cache workload ID credentials until refresh is needed; never log tokens."""
    def __init__(self, audience: str):
        self.audience = audience
        self.credentials = None
        self.lock = threading.Lock()

    def __call__(self) -> str:
        from google.auth.transport.requests import Request
        from google.oauth2.id_token import fetch_id_token_credentials
        with self.lock:
            if self.credentials is None:
                self.credentials = fetch_id_token_credentials(self.audience, request=Request())
            expiry = self.credentials.expiry
            if not self.credentials.token or expiry is None or expiry.replace(tzinfo=UTC) <= datetime.now(UTC) + timedelta(minutes=2):
                self.credentials.refresh(Request())
            return self.credentials.token


def make_header_provider(settings: Settings, caller: str, token_provider=None):
    if caller not in settings.trusted_callers:
        raise ValueError("MCP caller must be in the configured trusted caller set.")
    token_provider = token_provider or IdentityTokenProvider(settings.audience)

    async def headers(context):
        # ADK supplies ReadonlyContext, never the model or tool arguments.
        state = context.state if context else {}
        now = int(time.time())
        issued = now - now % 60
        principal = Scope(user_id=state.get("user:user_id", ""), store_id=state.get("user:store_id", ""),
            role=state.get("user:role", ""), namespace=settings.namespace, environment=settings.environment,
            audience=settings.audience, caller=caller, issued_at=issued, expires_at=issued + 180)
        token = await asyncio.to_thread(token_provider)
        return {"Authorization": "Bearer " + token, "X-Cymbal-Caller-Token": token,
                "X-Cymbal-Session": sign_scope(principal, settings.scope_key)}

    return headers


@cache
def _runtime_token_provider(audience: str):
    # Created only after invocation starts, never while an App is packaged.
    return IdentityTokenProvider(audience)


@dataclass(frozen=True)
class RuntimeHeaderProvider:
    """Serializable connection metadata only; secrets/credentials stay at runtime."""
    audience: str
    caller: str
    namespace: str
    environment: str

    async def __call__(self, context):
        secret = os.environ.get("CYMBAL_MCP_SCOPE_KEY", "")
        if not secret:
            raise RuntimeError("CYMBAL_MCP_SCOPE_KEY must be supplied by a pinned runtime secret reference.")
        settings = Settings(self.audience, secret, frozenset({self.caller}), self.namespace, self.environment)
        provider = make_header_provider(settings, self.caller, _runtime_token_provider(self.audience))
        return await provider(context)


class PlainResultMcpTool(McpTool):
    """Return the tool's own result dict, as the local function would, instead of the MCP envelope.

    ADK passes back the whole CallToolResult (the result as text and again as structured content). The model, the
    trace and the evaluation metrics read the same dict a local call returns, at half the tokens."""

    async def run_async(self, *, args, tool_context):
        result = await super().run_async(args=args, tool_context=tool_context)
        if not isinstance(result, dict) or "content" not in result and "structuredContent" not in result:
            return result
        text = "".join(part.get("text", "") for part in result.get("content", []) if part.get("type") == "text")
        if result.get("isError"):
            return {"status": "ERROR", "error_details": text or "The MCP server returned an error.", "source": "mcp"}
        return result.get("structuredContent") or json.loads(text)


class ScopedMcpToolset(McpToolset):
    """Discover remote capabilities only after the trusted session is signed in."""

    async def get_tools(self, readonly_context=None):
        state = readonly_context.state if readonly_context else {}
        if not all(state.get(key) for key in ("user:user_id", "user:store_id", "user:role")):
            return []
        # Malformed complete scope still fails in the signed header provider.
        tools = await super().get_tools(readonly_context=readonly_context)
        for tool in tools:
            # ADK returns its own McpTool subclass; give each tool the plain-result behaviour on top of its own class
            if isinstance(tool, McpTool) and not isinstance(tool, PlainResultMcpTool):
                tool.__class__ = type("PlainResult" + type(tool).__name__, (PlainResultMcpTool, type(tool)), {})
        return tools


def mcp_configured() -> bool:
    return bool(os.environ.get("CYMBAL_MCP_URL", "").strip())


def make_operational_mcp_toolset(tool_filter: list[str] | None = None) -> McpToolset | None:
    """The store reads served by the MCP server, optionally limited to one agent's tools.

    Returns None only when nothing MCP-related is configured (a local run reading BigQuery with the developer's own
    credentials); a partial configuration fails. deployment/deploy.py refuses to deploy without it."""
    url = os.environ.get("CYMBAL_MCP_URL", "").strip()
    if not url:
        if any(os.environ.get(name) for name in ("CYMBAL_MCP_AUDIENCE", "CYMBAL_MCP_SCOPE_KEY",
                                               "CYMBAL_MCP_CALLER_SERVICE_ACCOUNT")):
            raise ValueError("CYMBAL_MCP_URL is required when MCP authentication is configured.")
        return None
    required = ("CYMBAL_MCP_AUDIENCE", "CYMBAL_MCP_CALLER_SERVICE_ACCOUNT",
                "WORKSHOP_NAMESPACE", "STORE_OPS_ENV")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise ValueError("Missing MCP client configuration: " + ", ".join(missing))
    audience = os.environ[required[0]].rstrip("/")
    parsed = urlsplit(url)
    if f"{parsed.scheme}://{parsed.netloc}" != audience or parsed.path != "/mcp" or parsed.query or parsed.fragment:
        raise ValueError("CYMBAL_MCP_URL must be CYMBAL_MCP_AUDIENCE + /mcp.")
    caller = os.environ[required[1]]
    from agents.cymbal_store_ops.config import require_namespace
    namespace = require_namespace()
    environment = os.environ["STORE_OPS_ENV"]
    if not audience.startswith("https://") or not caller.endswith(".gserviceaccount.com") or environment not in {"dev", "preprod", "prod"}:
        raise ValueError("Invalid MCP audience, caller or environment.")
    return ScopedMcpToolset(connection_params=StreamableHTTPConnectionParams(url=url, timeout=30, sse_read_timeout=90),
        tool_filter=tool_filter or TOOLS, tool_list_cache_ttl_seconds=60,
        header_provider=RuntimeHeaderProvider(audience, caller, namespace, environment))


_CODE_TOOLSET = None


async def call_mcp_read(name: str, args: dict, tool_context) -> dict:
    """Call one MCP read from code (the briefing readers, report delivery, the end-of-day dashboard).

    Uses the signed-in person's scope from tool_context, like a model-chosen call. One toolset serves every caller."""
    global _CODE_TOOLSET
    if _CODE_TOOLSET is None:
        _CODE_TOOLSET = make_operational_mcp_toolset()
    tools = await _CODE_TOOLSET.get_tools(readonly_context=tool_context)
    tool = next((each for each in tools if each.name == name), None)
    if tool is None:
        raise RuntimeError(f"The MCP server does not offer {name}; redeploy the store MCP service.")
    return await tool.run_async(args=args, tool_context=tool_context)
