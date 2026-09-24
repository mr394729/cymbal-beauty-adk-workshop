"""Completed-day metrics and a real, versioned ADK PDF artifact."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from google.adk.tools import ToolContext
from google.genai import types

from agents.cymbal_store_ops import fixtures as F
from agents.cymbal_store_ops.chat_reply import ChatReply, NextAction
from agents.cymbal_store_ops.tools import data_backend
from agents.cymbal_store_ops.tools.data_backend import NOW, err, ok


def _scope(context) -> tuple[str | None, dict | None]:
    state = context.state if context else {}
    if (
        not state.get("user:user_id")
        or not state.get("user:store_id")
        or state.get("user:role") not in {"store_manager", "district_manager"}
    ):
        return None, err(
            "A signed-in manager is required for end-of-day reports.", code="forbidden"
        )
    return state["user:store_id"], None


def _dates(value: str) -> tuple[str, str]:
    today = NOW.astimezone(ZoneInfo(F.FIXTURE_TIMEZONE)).date()
    if value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Use a business date in YYYY-MM-DD format.")
    day = date.fromisoformat(value) if value else today - timedelta(days=1)
    if day >= today:
        raise ValueError(
            "End-of-day reports require a completed day; current-day traffic is a forecast."
        )
    return day.isoformat(), (day - timedelta(days=1)).isoformat()


def build_metrics(source: dict, business_date: str, comparison_date: str) -> dict:
    """Validate completeness and reconciliation before any prose or PDF is generated."""
    if not source.get("store"):
        return err("Store not found.", code="not_found")
    days = {row["business_date"]: row for row in source["days"]}
    opens, closes = source["store"]["opens"], source["store"]["closes"]
    expected_hours = int(closes.split(":")[0]) - int(opens.split(":")[0])
    if expected_hours <= 0 or opens[-2:] != "00" or closes[-2:] != "00":
        return err(
            "This report requires the store's complete hourly trading window.",
            code="unsupported_hours",
        )
    missing, invalid = [], []
    for day in (comparison_date, business_date):
        row = days.get(day, {})
        if row.get("traffic_rows") != expected_hours or row.get("traffic_hours") != expected_hours:
            missing.append(f"complete historical traffic for {day}")
        if not row.get("pos_rows"):
            missing.append(f"daily product sales for {day}")
        elif row.get("invalid_pos_rows") or row.get("pos_sales_cents") != row.get("sales_cents"):
            invalid.append(f"product sales reconciliation for {day}")
        if any(
            row.get(k) is not None and row[k] < 0
            for k in ("sales_cents", "transactions", "visitors", "units")
        ):
            invalid.append(f"nonnegative trading metrics for {day}")
    if not source.get("attendance_rows"):
        missing.append(f"worked attendance for {business_date}")
    if not source.get("previous_attendance_rows"):
        missing.append(f"worked attendance for {comparison_date}")
    if source.get("invalid_previous_attendance_rows"):
        invalid.append("prior worked attendance durations")
    if source.get("invalid_attendance_rows"):
        invalid.append("worked attendance durations")
    if source.get("staff_count", 0) > 25 or source.get("staff_count") != len(
        source.get("staff", [])
    ):
        invalid.append("complete staff list within the report limit")
    if sum(r["paid_minutes"] for r in source.get("staff", [])) != (source.get("paid_minutes") or 0):
        invalid.append("worked attendance totals")
    if missing or invalid:
        return err(
            "Report inputs are incomplete or inconsistent.",
            code="incomplete_report",
            missing_sources=missing,
            validation_errors=invalid,
        )

    def totals(day):
        r = days[day]
        return {
            **{k: r[k] for k in ("sales_cents", "transactions", "visitors", "units")},
            "paid_minutes": source["paid_minutes"]
            if day == business_date
            else source["previous_paid_minutes"],
            "average_basket_cents": round(r["sales_cents"] / r["transactions"], 2)
            if r["transactions"]
            else None,
        }

    metrics = dict(
        store_id=source["store"]["store_id"],
        store_name=source["store"]["city"],
        store=source["store"],
        business_date=business_date,
        comparison_date=comparison_date,
        timezone=F.FIXTURE_TIMEZONE,
        current=totals(business_date),
        previous=totals(comparison_date),
        hourly=source["hourly"],
        top_products=source["top_products"],
        top_product_ranking="units sold descending; product ID breaks ties",
        staff=source["staff"],
        staff_count=source["staff_count"],
        paid_minutes=source["paid_minutes"],
        issues=source["issues"],
        source_status={
            k: "available"
            for k in (
                "historical_traffic",
                "daily_product_sales",
                "worked_attendance",
                "loss_events",
                "guest_feedback",
            )
        },
    )
    from agents.cymbal_store_ops.reports.metrics import commercial_metrics

    metrics["commercial"] = commercial_metrics(metrics, source)
    metrics["metrics_digest"] = hashlib.sha256(
        json.dumps(metrics, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    return ok([metrics])


async def _read_metrics(
    business_date: str = "", tool_context: ToolContext | None = None
) -> dict:
    """Read complete historical store/day metrics before writing an end-of-day PDF.

    Defaults to the last completed store-local day. Includes prior-day comparison,
    conversion, units/basket, unit revenue, sales/paid-hour, category/product mix,
    average-basket changes, worked staff and dated loss/guest issues. These are
    observations, not proof of cause; monetary ratios are cents per unit/transaction
    or paid hour, while conversion changes are percentage points. Missing feeds
    produce an explicit error. Retain metrics_digest for create_end_of_day_dashboard.
    """
    store, error = _scope(tool_context)
    if error:
        return error
    try:
        day, previous = _dates(business_date)
    except ValueError as exc:
        return err(str(exc), code="invalid_argument")
    backend = data_backend.make_backend()
    source = await asyncio.to_thread(
        backend.get_end_of_day_report_data,
        store_id=store,
        business_date=day,
        comparison_date=previous,
    )
    if source.get("status") != "SUCCESS":
        return source
    if len(source.get("rows", [])) != 1:
        return err("Expected one complete store report payload.", code="source_error")
    if (source["rows"][0].get("store") or {}).get("store_id") != store:
        return err("Report source returned a different store.", code="scope_mismatch")
    return build_metrics(source["rows"][0], day, previous)


async def get_end_of_day_metrics(
    business_date: str = "", tool_context: ToolContext | None = None
) -> dict:
    """Read concise completed-day commercial evidence before writing an end-of-day PDF.

    Defaults to the last completed store-local day. Includes current/prior sales,
    transactions, visitors, units, actual worked hours, denominator-labelled ratios,
    distinct transaction and conversion peaks, product/category comparisons and dated
    issues. Observations do not establish causes. Full chart and staff records stay
    with the renderer; no narrative needs to reproduce them. Missing feeds return an
    error. Retain the date and metrics_digest for create_end_of_day_dashboard.
    """
    result = await _read_metrics(business_date, tool_context)
    if result.get("status") != "SUCCESS":
        return result
    metrics = result["rows"][0]
    keys = (
        "store_id", "store_name", "business_date", "comparison_date", "timezone",
        "current", "previous", "commercial", "top_products", "top_product_ranking",
        "staff_count", "paid_minutes", "issues", "source_status", "metrics_digest",
    )
    return ok([{key: metrics[key] for key in keys}])


def narrative(summary: str, went_well: list[str], follow_up: list[str], headline: str = "") -> dict:
    """Small plain-text slots; the model cannot supply layout, URLs or numeric chart data."""

    def text(value, max_chars, max_words):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Narrative items must be nonempty text.")
        value = " ".join(value.split())
        if len(value) > max_chars or len(value.split()) > max_words:
            raise ValueError("Narrative is too long for the one-page report.")
        if any(ord(c) < 32 for c in value):
            raise ValueError("Narrative contains unsupported control characters.")
        return value

    if (
        not isinstance(went_well, list)
        or not isinstance(follow_up, list)
        or max(len(went_well), len(follow_up)) > 2
    ):
        raise ValueError("Use at most two short items in each narrative section.")
    return dict(
        headline=text(headline, 90, 14) if headline else "",
        summary=text(summary, 280, 45),
        went_well=[text(s, 145, 24) for s in went_well],
        follow_up=[text(s, 145, 24) for s in follow_up],
    )


async def create_end_of_day_dashboard(
    business_date: str,
    metrics_digest: str,
    headline: str,
    summary: str,
    went_well: list[str],
    follow_up: list[str],
    next_actions: list[dict[str, str]],
    tool_context: ToolContext | None = None,
) -> dict:
    """Create an A4 PDF artifact from verified metrics and brief, evidence-grounded prose.

    First call get_end_of_day_metrics and use its date/digest. You write the report's
    judgement; the template already prints every number, chart and table, so do not
    restate the metric cards. The headline (<=14 words, <=90 characters) states the
    day's main finding in plain words, such as which category or hour carried the day
    or where it slipped. The summary (<=45 words, <=280 characters) explains what the
    figures mean together. At most two <=24-word items per narrative section (each
    also <=145 characters), each linking figures that explain each other, grounded
    only in those metrics. Compare observed ratios with their denominators. Words such as
    drove, driven by, because of, led to or thanks to claim a cause the figures cannot show; say that
    figures moved together with while or alongside instead. Do not claim causal sales contributions, discount/mix causes, or product-specific stock
    complaints that the evidence does not establish. Follow-up should identify the
    relevant observed exception or commercial tension and what to verify next; do
    not claim a cause or a completed action. The template supplies all numbers, charts and tables.
    Supply 3–5 useful next_actions with label and prompt, grounded in these findings
    and available capabilities. Continue the report's material findings rather than
    offering unrelated opening work. Do not read extra data just to populate suggestions.
    This creates a document, not store tasks. Returns its actual ADK artifact version.
    A successful sole coordinator call displays your summary and next_actions directly,
    without another rewrite. Mixed tool-call batches retain coordinator synthesis.
    """
    _, error = _scope(tool_context)
    if error:
        return error
    try:
        prose = narrative(summary, went_well, follow_up, headline)
        reply = ChatReply(answer="End-of-day report ready.\n\n" + prose["summary"],
                          next_actions=[NextAction.model_validate(a) for a in next_actions])
        if not reply.next_actions:
            raise ValueError("Report delivery requires 3–5 next_actions.")
    except ValueError as exc:
        return err(str(exc), code="invalid_argument")
    from agents.cymbal_store_ops.mcp_connection import (  # the catalog imports this module
        call_mcp_read,
        mcp_configured,
    )

    if mcp_configured():
        # Deployed: the full metrics come from the MCP server, like every other store read
        fresh = await call_mcp_read("read_end_of_day_report", {"business_date": business_date}, tool_context)
    else:
        fresh = await _read_metrics(business_date, tool_context)
    if fresh.get("status") != "SUCCESS":
        return fresh
    metrics = fresh["rows"][0]
    if metrics_digest != metrics["metrics_digest"]:
        return err(
            "Report data changed. Read the metrics again before drafting this report.",
            code="stale_metrics",
            current_metrics_digest=metrics["metrics_digest"],
        )
    from agents.cymbal_store_ops.reports.render import TEMPLATE_VERSION, render_pdf

    try:
        pdf = await render_pdf(metrics, prose)
    except (RuntimeError, ValueError, TimeoutError) as exc:
        return err(f"The PDF could not be rendered: {exc}", code="render_error")
    filename = f"cymbal-{metrics['store_id']}-{metrics['business_date']}-end-of-day.pdf"
    version = await tool_context.save_artifact(
        filename,
        types.Part.from_bytes(data=pdf, mime_type="application/pdf"),
        custom_metadata={
            "store_id": metrics["store_id"],
            "business_date": metrics["business_date"],
            "report_kind": "end_of_day",
            "metrics_digest": metrics_digest,
            "template_version": TEMPLATE_VERSION,
        },
    )
    result = ok(
        [],
        artifact={
            "filename": filename,
            "version": version,
            "mime_type": "application/pdf",
            "business_date": metrics["business_date"],
            "byte_count": len(pdf),
        },
    )
    from agents.cymbal_store_ops.tools.report_delivery import _sole_current_call

    inv = tool_context.get_invocation_context()
    result["reply_completed"] = False
    if inv.agent.name == "store_manager_agent" and _sole_current_call(tool_context, "create_end_of_day_dashboard"):
        result["reply_completed"] = True
        result["final_reply"] = {**reply.model_dump(), "invocation_id": inv.invocation_id,
                                 "call_id": tool_context.function_call_id}
        tool_context.actions.skip_summarization = True
    return result
