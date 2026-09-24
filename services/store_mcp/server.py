"""Stateless Streamable HTTP MCP server for the store reads: trusted caller, signed session scope, the agent's own read functions."""
from __future__ import annotations

import asyncio
import inspect
import os
from types import SimpleNamespace
from urllib.parse import urlsplit

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse

from agents.cymbal_store_ops.callbacks import (
    enforce_role_before_tool,
    enforce_store_scope_before_tool,
)
from agents.cymbal_store_ops.mcp_auth import GoogleCallerVerifier, Settings, verify_scope
from agents.cymbal_store_ops.mcp_catalog import READS
from agents.cymbal_store_ops.tools import domain_tools, end_of_day, inventory_summary, store_query
from agents.cymbal_store_ops.tools.data_backend import err
from agents.cymbal_store_ops.tools.store_query import (
    DiscoveryResource,
    Measure,
    RecordFilter,
    RecordOrder,
    ResourceName,
)


class ScopedAuthentication:
    def __init__(self, app, settings, verifier):
        self.app, self.settings, self.verifier = app, settings, verifier

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        token = request.headers.get("x-cymbal-caller-token", "")
        signed_scope = request.headers.get("x-cymbal-session", "")
        if not token or not signed_scope:
            return await JSONResponse({"error": "Authenticated caller and signed session required."}, 401)(scope, receive, send)
        try:
            claims = await asyncio.to_thread(self.verifier, token, self.settings.audience)
            caller = claims.get("email")
            if caller not in self.settings.trusted_callers or claims.get("email_verified") is not True:
                raise ValueError("Untrusted caller.")
            principal = verify_scope(signed_scope, self.settings, caller)
        except (ValueError, TypeError):
            return await JSONResponse({"error": "Invalid caller or session scope."}, 403)(scope, receive, send)
        scope.setdefault("state", {})["store_scope"] = principal
        await self.app(scope, receive, send)


def _context(ctx: Context):
    request = ctx.request_context.request
    if request is None or not getattr(request.state, "store_scope", None):
        raise ValueError("A verified session is required.")
    return SimpleNamespace(state=request.state.store_scope.state(), user_content=None)


def _remote(function):
    """Wrap one read function as an MCP tool: its own parameters, minus tool_context, plus the MCP request context."""
    signature = inspect.signature(function, eval_str=True)
    takes_context = "tool_context" in signature.parameters
    # tool_context comes from the signed session; delivery is the agent's on-screen report option, not an MCP read
    parameters = [p for name, p in signature.parameters.items() if name not in ("tool_context", "delivery")]
    parameters.append(inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context))

    async def call(ctx: Context, **arguments) -> dict:
        context = _context(ctx)
        # The same checks the agent runs before every tool call: the signed-in store (another store only for a
        # district manager) and the role. The server enforces them itself; it does not trust the caller to have.
        for guard in (enforce_store_scope_before_tool, enforce_role_before_tool):
            if blocked := guard(SimpleNamespace(name=function.__name__), arguments, context):
                return blocked
        if takes_context:
            arguments["tool_context"] = context
        if inspect.iscoroutinefunction(function):
            return await function(**arguments)
        return await asyncio.to_thread(function, **arguments)

    call.__name__, call.__doc__ = function.__name__, inspect.getdoc(function)
    call.__signature__ = signature.replace(parameters=parameters, return_annotation=dict)
    return call


def create_mcp(settings: Settings) -> FastMCP:
    host = urlsplit(settings.audience).netloc
    mcp = FastMCP("Cymbal Store Operations", stateless_http=True, json_response=True,
                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
                    allowed_hosts=[host, "testserver", "127.0.0.1:*", "localhost:*"],
                    allowed_origins=[settings.audience]))
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

    @mcp.tool(annotations=read)
    async def describe_store_data(ctx: Context, resource: DiscoveryResource = "") -> dict:
        """Discover scoped read resources, field types and enum values. No records are read."""
        result = store_query.describe_store_data(resource, tool_context=_context(ctx))
        if result.get("status") == "SUCCESS":
            result["delivery_modes"] = {"answer": "Bounded pages with full matching counts; no UI report through this service."}
        return result

    @mcp.tool(annotations=read)
    async def get_product_details(product_id: str, ctx: Context) -> dict:
        """Exact catalog attributes and latest three dated reviews for a product carried by this store.

        Reviews are catalog-wide, not local guest feedback; their sample is not a population finding.
        """
        member = await asyncio.to_thread(inventory_summary.get_product_stock, product_id, tool_context=_context(ctx))
        if member.get("status") != "SUCCESS":
            return member
        if not member["rows"]:
            return err("No inventory membership for this product at the signed-in store.", code="not_found")
        return await asyncio.to_thread(domain_tools.get_product_details, product_id)

    @mcp.tool(annotations=read)
    async def read_store_report(resource: ResourceName, ctx: Context, fields: list[str] | None = None,
            filters: list[RecordFilter] | None = None, group_by: list[str] | None = None,
            measures: list[Measure] | None = None, order_by: list[RecordOrder] | None = None,
            store_id: str = "") -> dict:
        """Rows for an on-screen report and CSV: the same query as query_store_data, up to 5,000 rows, one page."""
        context = _context(ctx)
        for guard in (enforce_store_scope_before_tool, enforce_role_before_tool):
            if blocked := guard(SimpleNamespace(name="query_store_data"), {"store_id": store_id}, context):
                return blocked
        result = await asyncio.to_thread(store_query.query_store_data, resource, fields, filters, group_by, measures,
                                         order_by, store_id=store_id, delivery="report", tool_context=context)
        if result.get("status") == "SUCCESS":
            result["report"] = context.state.get("ui:report")
        return result

    @mcp.tool(annotations=read)
    async def read_end_of_day_report(ctx: Context, business_date: str = "") -> dict:
        """Full completed-day metrics for the end-of-day PDF: charts, staff and issues, with the metrics digest."""
        return await end_of_day._read_metrics(business_date, _context(ctx))

    # Every other store read the agent makes, registered from the shared catalog with the same name, arguments and
    # description as the agent's own tool. The session scope replaces the ADK ToolContext the function expects.
    registered = {tool.name for tool in mcp._tool_manager.list_tools()}
    for name, function in READS.items():
        if name not in registered:
            mcp.add_tool(_remote(function), name=name, description=inspect.getdoc(function), annotations=read)
    return mcp


def create_app(settings: Settings | None = None, verifier=None):
    settings = settings or Settings.from_env()
    # Production configuration must target this deployment's dataset, never a header-supplied dataset.
    if verifier is None:
        from agents.cymbal_store_ops.config import load_env_config
        cfg = load_env_config()
        if cfg.namespace != settings.namespace or cfg.env != settings.environment:
            raise ValueError("MCP scope and configured dataset namespace/environment disagree.")
    mcp = create_mcp(settings)
    app = mcp.streamable_http_app()
    app.add_middleware(ScopedAuthentication, settings=settings, verifier=verifier or GoogleCallerVerifier())
    return app


def main():
    import uvicorn
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), access_log=False)


if __name__ == "__main__":
    main()
