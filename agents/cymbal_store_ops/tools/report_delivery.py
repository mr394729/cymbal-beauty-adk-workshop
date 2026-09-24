"""Coordinator query and final-report capabilities over the shared scoped query engine."""
from __future__ import annotations

import asyncio

from google.adk.tools import ToolContext
from pydantic import ValidationError

from agents.cymbal_store_ops.chat_reply import ChatReply, NextAction
from agents.cymbal_store_ops.mcp_connection import call_mcp_read, mcp_configured
from agents.cymbal_store_ops.tools import store_query
from agents.cymbal_store_ops.tools.data_backend import err
from agents.cymbal_store_ops.tools.store_query import (
    DiscoveryResource,
    Measure,
    RecordFilter,
    RecordOrder,
    ResourceName,
)


def query_store_data(resource: ResourceName, fields: list[str] | None = None, filters: list[RecordFilter] | None = None,
                     group_by: list[str] | None = None, measures: list[Measure] | None = None,
                     order_by: list[RecordOrder] | None = None, limit: int = 25, offset: int = 0,
                     store_id: str = "", tool_context: ToolContext | None = None) -> dict:
    """Read or aggregate scoped records for analysis using chosen fields, filters, groups and measures.

    Resources and field/enum contracts are available through describe_store_data.
    Filters are ANDed; values are strings converted to field types. Aggregates use
    every matching record before pagination. Pages contain 1–100 rows and full
    matching counts; an incomplete page is not the full result. No raw SQL.
    This read does not display a report or finish the conversation.
    """
    return store_query.query_store_data(resource, fields, filters, group_by, measures, order_by,
                                       limit, offset, store_id, tool_context=tool_context)


def describe_store_data(resource: DiscoveryResource = "", tool_context: ToolContext | None = None) -> dict:
    """Discover scoped resources, fields, enum values and limitations for flexible queries and reports.

    query_store_data returns records or aggregates for analysis. deliver_store_report
    displays the same chosen query as a table/CSV and completes the reply when that
    report satisfies the current request. Report delivery requires 3–5 dynamically
    chosen follow-up requests; it is not appropriate when further analysis remains.
    """
    result = store_query.describe_store_data(resource, tool_context)
    if result.get("status") == "SUCCESS":
        result.pop("delivery_modes", None)
        result["query_tools"] = {
            "query_store_data": "Read selected records/aggregates, 1–100 rows per page, full matching count; continue analysis as needed.",
            "deliver_store_report": "Deliver the chosen query as a table/CSV with up to 5,000 rows and explicit completeness; provide 3–5 dynamic next_actions. Finishes a sole coordinator call on success; mixed calls retain normal synthesis.",
        }
    return result


def _sole_current_call(context, tool_name="deliver_store_report"):
    inv = context.get_invocation_context()
    if context.tool_confirmation is not None:
        return False
    if inv.user_content and any(part.function_response for part in inv.user_content.parts or []):
        return False
    call_id = context.function_call_id
    if not call_id:
        return False
    for event in reversed(inv.session.events):
        if event.invocation_id != inv.invocation_id or event.author != "store_manager_agent" or event.partial:
            continue
        calls = event.get_function_calls()
        if any(call.id == call_id and call.name == tool_name for call in calls):
            return len(calls) == 1 and not event.actions.requested_tool_confirmations
    return False


async def deliver_store_report(resource: ResourceName, next_actions: list[NextAction], fields: list[str] | None = None,
                         filters: list[RecordFilter] | None = None, group_by: list[str] | None = None,
                         measures: list[Measure] | None = None, order_by: list[RecordOrder] | None = None,
                         store_id: str = "", tool_context: ToolContext | None = None) -> dict:
    """Deliver a chosen scoped query as a searchable table/CSV when ready to finish the user's request.

    Choose resource, columns, filters, grouping, measures and ordering freely using
    describe_store_data contracts. Aggregates cover all matching records. Reports
    contain the first 5,000 rows with explicit full matching count and completeness.
    Rows go directly to the UI; this tool returns metadata only. Supply 3–5 useful,
    model-written next_actions grounded in the conversation and permitted role,
    preserving known IDs and constraints without inventing observations or fetching
    data to populate activities. No hardcoded activities or introductory claims.
    A successful sole coordinator call completes the reply without another model
    rewrite. For unfinished analysis use query_store_data. A mixed tool-call batch
    displays the report but leaves synthesis active. Errors never end the turn.
    """
    if tool_context is None or not hasattr(tool_context, "get_invocation_context"):
        return err("Report delivery requires the active coordinator context.", code="invalid_context")
    inv = tool_context.get_invocation_context()
    if inv.agent.name != "store_manager_agent":
        return err("Final report delivery is a coordinator capability.", code="invalid_context")
    try:
        actions = [NextAction.model_validate(action) for action in next_actions]
        if not 3 <= len(actions) <= 5:
            raise ValueError("Report delivery requires 3–5 next_actions.")
    except (ValidationError, ValueError, TypeError) as error:
        return err(str(error), code="invalid_next_actions")
    if mcp_configured():
        # Deployed: the rows come from the MCP server; the table is shown from this session
        result = await call_mcp_read("read_store_report", {
            "resource": resource, "fields": fields, "filters": filters, "group_by": group_by,
            "measures": measures, "order_by": order_by, "store_id": store_id}, tool_context)
        if result.get("status") == "SUCCESS":
            tool_context.state["ui:report"] = result.pop("report")
    else:
        result = await asyncio.to_thread(store_query.query_store_data, resource, fields, filters, group_by, measures,
                                         order_by, store_id=store_id, delivery="report", tool_context=tool_context)
    if result.get("status") != "SUCCESS":
        return result
    result["report_already_displayed"] = True
    if not _sole_current_call(tool_context):
        result["reply_completed"] = False
        return result
    count, total = result["row_count"], result["total_matching"]
    title = resource.replace("_", " ").capitalize()
    answer = f"{title} report ready: {count:,} of {total:,} matching records."
    if not result["complete"]:
        answer += " This report is partial; narrow the filters to reduce the matching set."
    reply = ChatReply(answer=answer, next_actions=actions)
    result["reply_completed"] = True
    result["final_reply"] = {**reply.model_dump(), "invocation_id": inv.invocation_id,
                             "call_id": tool_context.function_call_id}
    tool_context.actions.skip_summarization = True
    return result
