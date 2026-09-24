"""Read the known briefing inputs concurrently; reserve model calls for deciding priorities.

Each branch is a deterministic ADK workflow node, not an LLM specialist. It emits the actual
tool calls/results and enforces the same scope/role callbacks as interactive tools.

ADK docs:
  Parallel fan-out and gather: https://adk.dev/workflows/patterns/#parallel-fan-out-and-gather
  Custom agents: https://adk.dev/agents/custom-agents/
Workshop pages: docs/patterns/04-parallel-fan-out.md
"""
from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from collections.abc import Callable

from google.adk.agents import BaseAgent
from google.adk.events import Event, EventActions
from google.adk.tools import FunctionTool, ToolContext
from google.genai import types

from agents.cymbal_store_ops.callbacks import (
    enforce_role_before_tool,
    enforce_store_scope_before_tool,
)
from agents.cymbal_store_ops.mcp_catalog import READS
from agents.cymbal_store_ops.mcp_connection import call_mcp_read, mcp_configured
from agents.cymbal_store_ops.sub_agents.briefing_facts import project_briefing_facts
from agents.cymbal_store_ops.tools import domain_tools as domain
from agents.cymbal_store_ops.tools.inventory_context import get_inventory_context
from agents.cymbal_store_ops.tools.operations_tools import (
    get_coverage_requirements,
    get_loss_controls,
    get_merchandising_work,
)
from agents.cymbal_store_ops.tools.pickup_workload import get_pickup_workload
from agents.cymbal_store_ops.trace import finish_span, result_status, start_span


class BriefingSignals(BaseAgent):
    area: str
    output_key: str

    async def _read(self, ctx, function: Callable, args: dict, call_id: str):
        tool = FunctionTool(function)
        context = ToolContext(ctx, function_call_id=call_id)
        span_id = start_span(context, kind="tool", name=function.__name__, inputs=args, span_id=call_id)
        try:
            for guard in (enforce_store_scope_before_tool, enforce_role_before_tool):
                if blocked := guard(tool, args, context):
                    finish_span(context, span_id, output=blocked, status="blocked")
                    return blocked
            if mcp_configured() and function.__name__ in READS:
                # Deployed: the same read, served by the MCP server under the signed-in person's scope.
                result = await call_mcp_read(function.__name__, args, context)
            elif inspect.iscoroutinefunction(function):
                result = await function(**args, tool_context=context)
            else:
                result = await asyncio.to_thread(function, **args, tool_context=context)
        except Exception as error:
            # Observability records the failure and preserves the framework's original error path.
            finish_span(context, span_id, output={"error_type": type(error).__name__}, status="error")
            raise
        finish_span(context, span_id, output=result, status=result_status(result))
        return result

    async def _batch(self, ctx, calls, results):
        identifiers = [str(uuid.uuid4()) for _ in calls]
        yield Event(author=self.name, invocation_id=ctx.invocation_id,
            content=types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(
                name=fn.__name__, args=args, id=cid)) for (fn, args), cid in zip(calls, identifiers, strict=True)]))
        # Tasks are read-only and operate on separate ToolContexts. Writes never use this path.
        values = await asyncio.gather(*(self._read(ctx, fn, args, cid) for (fn, args), cid in zip(calls, identifiers, strict=True)))
        for (fn, _), cid, value in zip(calls, identifiers, values, strict=True):
            results[fn.__name__] = value
            yield Event(author=self.name, invocation_id=ctx.invocation_id,
                content=types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
                    name=fn.__name__, id=cid, response=value))]))

    async def _run_async_impl(self, ctx):
        calls = {
            "inventory": [(domain.get_osa_exceptions, {"limit": 3}), (domain.get_bopis_demand, {}),
                          (domain.get_task_status, {}), (get_merchandising_work, {})],
            "coverage": [(domain.get_traffic_and_backlog, {"hours": 4}),
                         (domain.get_shift_roster, {"window_hours": 4}),
                         (domain.get_guest_feedback, {"days": 7}), (get_coverage_requirements, {}),
                         (get_pickup_workload, {"hours": 2})],
            "shrink": [(domain.get_shrink_signals, {"days": 14})],
        }[self.area]
        results = {}
        async for event in self._batch(ctx, calls, results):
            yield event
        if self.area == "inventory":
            exceptions = results["get_osa_exceptions"].get("rows", [])
            if exceptions:
                async for event in self._batch(ctx, [(get_inventory_context,
                        {"product_name": exceptions[0]["product_id"]})], results):
                    yield event
        if self.area == "shrink":
            signals = results["get_shrink_signals"]
            products = signals.get("products", [])
            if products:
                product_id = products[0]["product_id"]
                async for event in self._batch(ctx, [(domain.get_task_history, {"product_id": product_id}),
                                                    (get_loss_controls, {"product_id": product_id})], results):
                    yield event
        # JSON retains exact units and pickup windows; no intermediate paraphrase can alter them.
        payload = json.dumps(project_briefing_facts(self.area, results), ensure_ascii=False, default=str,
                             separators=(",", ":"))
        yield Event(author=self.name, invocation_id=ctx.invocation_id,
                    actions=EventActions(state_delta={self.output_key: payload}))
