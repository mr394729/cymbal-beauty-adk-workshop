"""Historical reconciliation, scoped reports, HTML and real ADK artifact storage."""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime
from io import BytesIO
from types import SimpleNamespace

import pytest

from agents.cymbal_store_ops.reporting_fixtures import REPORT_TABLE_COUNTS, generate_report_tables
from agents.cymbal_store_ops.reports.render import render_html
from agents.cymbal_store_ops.tools import end_of_day as reports
from agents.cymbal_store_ops.tools.backends.reporting import bigquery_report_data
from tests.conftest import FakeToolContext
from tests.unit.test_report_delivery import ACTIONS


def manager(store="S-014"):
    return FakeToolContext(
        {"user:user_id": "U-M014", "user:store_id": store, "user:role": "store_manager"}
    )


@pytest.mark.asyncio
async def test_completed_day_reconciles_and_excludes_current_forecast(fake_backend):
    result = await reports.get_end_of_day_metrics(tool_context=manager())
    assert result["status"] == "SUCCESS", result
    m = result["rows"][0]
    assert (m["business_date"], m["comparison_date"]) == ("2026-10-02", "2026-10-01")
    assert m["current"]["sales_cents"] == 797088 and m["previous"]["sales_cents"] == 700688
    assert m["current"]["transactions"] == 169 and m["previous"]["transactions"] == 146
    assert m["current"]["units"] == 236 and m["previous"]["units"] == 201
    assert m["paid_minutes"] == 3390 and m["staff_count"] == 8
    assert m["top_products"][0]["product_id"] == "P-0101"
    assert m["issues"]["low_guest_reviews"] == 1 and m["issues"]["guest_reviews"] == 4
    assert {i["event_type"]: i["value_cents"] for i in m["issues"]["loss_by_type"]} == {
        "return_anomaly": 850,
        "unknown_loss": 9500,
    }
    assert "hourly" not in m and "staff" not in m and len(m["metrics_digest"]) == 64


@pytest.mark.asyncio
@pytest.mark.parametrize("day", ["2026-10-03", "2026-10-04", "2026-1-2", "bad-date"])
async def test_rejects_forecast_future_and_noncanonical_date(fake_backend, day):
    assert (await reports.get_end_of_day_metrics(day, manager()))["code"] == "invalid_argument"


@pytest.mark.asyncio
async def test_missing_sources_and_other_store_never_become_zero(fake_backend):
    assert (await reports.get_end_of_day_metrics("2026-09-30", manager()))[
        "code"
    ] == "incomplete_report"
    assert (await reports.get_end_of_day_metrics(tool_context=manager("S-001")))[
        "code"
    ] == "incomplete_report"
    fake_backend.pos_daily_product_sales = []
    result = await reports.get_end_of_day_metrics(tool_context=manager())
    assert (
        result["code"] == "incomplete_report"
        and "daily product sales for 2026-10-02" in result["missing_sources"]
    )


@pytest.mark.asyncio
async def test_permissions_before_backend_read(monkeypatch):
    monkeypatch.setattr(reports.data_backend, "make_backend", lambda: pytest.fail("Forbidden read"))
    for state in (
        {},
        {"user:user_id": "A-1004", "user:store_id": "S-014", "user:role": "associate"},
    ):
        assert (await reports.get_end_of_day_metrics(tool_context=FakeToolContext(state)))[
            "code"
        ] == "forbidden"


@pytest.mark.asyncio
async def test_stale_digest_rejects_before_render_or_save(fake_backend):
    m = (await reports.get_end_of_day_metrics(tool_context=manager()))["rows"][0]
    fake_backend.feedback.append(
        {"store_id": "S-014", "submitted_at": "2026-10-03T01:00:00Z", "rating": 1}
    )
    result = await reports.create_end_of_day_dashboard(
        m["business_date"], m["metrics_digest"], "A steady day", "Review yesterday's trading.", [], [], ACTIONS, manager()
    )
    assert result["code"] == "stale_metrics"


@pytest.mark.asyncio
async def test_reconciliation_and_attendance_errors_visible(fake_backend):
    fake_backend.pos_daily_product_sales[0]["net_sales_cents"] += 1
    assert (await reports.get_end_of_day_metrics(tool_context=manager()))["validation_errors"]
    fake_backend.pos_daily_product_sales[0]["net_sales_cents"] -= 1
    fake_backend.worked_shifts[-1]["paid_minutes"] += 1
    assert (
        "worked attendance durations"
        in (await reports.get_end_of_day_metrics(tool_context=manager()))["validation_errors"]
    )


def test_generator_additive_deterministic_and_consistent():
    from data.generate import generate_all

    data = generate_all()
    original = copy.deepcopy(data)
    tables = generate_report_tables(data)
    assert data == original and tables == generate_report_tables(data)
    assert {k: len(v) for k, v in tables.items()} == REPORT_TABLE_COUNTS
    assert (
        len(
            {
                (r["store_id"], r["business_date"], r["product_id"])
                for r in tables["pos_daily_product_sales"]
            }
        )
        == 40
    )
    for row in tables["worked_shifts"]:
        minutes = (
            datetime.fromisoformat(row["clock_out"]) - datetime.fromisoformat(row["clock_in"])
        ).total_seconds() / 60
        assert minutes - row["unpaid_break_minutes"] == row["paid_minutes"]


@pytest.mark.asyncio
async def test_template_escapes_prose_and_uses_source_metrics(fake_backend):
    m = (await reports._read_metrics(tool_context=manager()))["rows"][0]
    prose = reports.narrative(
        '<script>alert("x")</script>', ["Sales and transactions increased."], []
    )
    html = render_html(m, prose)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "$7,970.88" in html and "236" in html and "Top products" in html
    with pytest.raises(ValueError):
        reports.narrative("word " * 46, [], [])
    with pytest.raises(ValueError):
        reports.narrative("Sales rose.", ["A", "B", "C"], [])


@pytest.mark.asyncio
async def test_bigquery_single_scoped_aggregate_json_boundary(fake_backend):
    expected = fake_backend.get_end_of_day_report_data(
        store_id="S-014", business_date="2026-10-02", comparison_date="2026-10-01"
    )
    calls = []

    def query(sql, params, **kwargs):
        calls.append((sql, params, kwargs))
        return [{"report_json": json.dumps(expected["rows"][0])}]

    result = bigquery_report_data(
        SimpleNamespace(_t=lambda n: f"`project.dataset.{n}`", _query=query),
        store_id="S-014",
        business_date="2026-10-02",
        comparison_date="2026-10-01",
    )
    assert result == expected and len(calls) == 1
    sql, params, kwargs = calls[0]
    assert "TO_JSON_STRING" in sql and "LIMIT 5" in sql and "LIMIT 25" in sql
    assert (
        "SELECT *" not in sql and params["store"] == "S-014" and params["tz"] == "America/Chicago"
    )
    assert "S-014" not in sql and kwargs["limit"] == 1


@pytest.mark.asyncio
async def test_real_tool_context_versions_without_binary_in_events(fake_backend, monkeypatch):
    from google.adk.agents import BaseAgent
    from google.adk.events import Event
    from google.adk.runners import InMemoryRunner
    from google.adk.tools import ToolContext
    from google.genai import types

    from agents.cymbal_store_ops.reports import render

    pdf = b"%PDF-1.7\nartifact-contract-test"

    async def render_bytes(*args):
        return pdf

    monkeypatch.setattr(render, "render_pdf", render_bytes)

    class ExportAgent(BaseAgent):
        async def _run_async_impl(self, context):
            tool = ToolContext(context)
            m = (await reports.get_end_of_day_metrics(tool_context=tool))["rows"][0]
            response = await reports.create_end_of_day_dashboard(
                m["business_date"],
                m["metrics_digest"],
                "Skincare carried a busier Friday",
                "Sales and transactions increased from the prior day.",
                ["More units sold."],
                ["Review the recorded loss events."],
                ACTIONS,
                tool,
            )
            yield Event(
                author=self.name,
                actions=tool.actions,
                content=types.Content(parts=[types.Part(text=json.dumps(response))]),
            )

    runner = InMemoryRunner(agent=ExportAgent(name="report_export"), app_name="report_test")
    session = await runner.session_service.create_session(
        app_name="report_test", user_id="owner-manager", state=manager().state
    )
    descriptors = []
    for _ in range(2):
        async for event in runner.run_async(
            user_id="owner-manager",
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text="Export the report")]),
        ):
            if event.actions.artifact_delta:
                descriptors.append(event.actions.artifact_delta)
                assert "PDF-" not in event.model_dump_json(
                    exclude_none=True
                ) and "inline_data" not in event.model_dump_json(exclude_none=True)
    filename = "cymbal-S-014-2026-10-02-end-of-day.pdf"
    assert descriptors == [{filename: 0}, {filename: 1}]
    for version in (0, 1):
        part = await runner.artifact_service.load_artifact(
            app_name="report_test",
            user_id="owner-manager",
            session_id=session.id,
            filename=filename,
            version=version,
        )
        assert part.inline_data.data == pdf and part.inline_data.mime_type == "application/pdf"
    saved = await runner.session_service.get_session(
        app_name="report_test", user_id="owner-manager", session_id=session.id
    )
    assert "PDF-" not in json.dumps(saved.state)


@pytest.mark.skipif(
    os.environ.get("RUN_PDF_RENDER_TESTS") != "1", reason="Explicit Chromium render check"
)
@pytest.mark.asyncio
async def test_actual_html_pdf_a4_one_page_with_source_metrics(fake_backend, tmp_path):
    from pypdf import PdfReader

    from agents.cymbal_store_ops.reports.render import render_pdf

    m = (await reports._read_metrics(tool_context=manager()))["rows"][0]
    prose = reports.narrative(
        "Sales and transactions increased from the previous day. Review the recorded loss events and the low guest rating when planning the next shift.",
        ["Sales reached $7,970.88, with 169 transactions.", "The team sold 236 units."],
        [
            "Review the recorded unknown-loss event and return anomaly.",
            "Review the one low rating among four guest reviews.",
        ],
    )
    pdf = await render_pdf(m, prose)
    (tmp_path / "end-of-day.pdf").write_bytes(pdf)
    pages = PdfReader(BytesIO(pdf)).pages
    assert len(pages) == 1
    text = pages[0].extract_text()
    for value in ("$7,970.88", "169", "236", "Top products", "Recorded issues", "What went well"):
        assert value in text


@pytest.mark.asyncio
async def test_commercial_metrics_keep_denominators_without_counterfactual_attribution(fake_backend):
    m = (await reports.get_end_of_day_metrics(tool_context=manager()))["rows"][0]
    c = m["commercial"]
    assert c["ratios"]["conversion_pct"]["current"] == pytest.approx(169 / 466 * 100, abs=0.0001)
    assert c["ratios"]["conversion_pct"]["previous"] == pytest.approx(146 / 440 * 100, abs=0.0001)
    assert c["ratios"]["units_per_transaction"]["current"] == pytest.approx(236 / 169, abs=0.0001)
    assert c["ratios"]["average_unit_revenue_cents"]["current"] == pytest.approx(
        797088 / 236, abs=0.0001
    )
    assert c["ratios"]["sales_per_paid_hour_cents"]["current"] == pytest.approx(
        797088 / 56.5, abs=0.0001
    )
    assert "sales_change_bridge" not in c
    basket = c["ratios"]["average_basket_cents"]
    assert basket["current"] == pytest.approx(797088 / 169, abs=0.0001)
    assert basket["previous"] == pytest.approx(700688 / 146, abs=0.0001)
    assert basket["change"] == pytest.approx(797088 / 169 - 700688 / 146, abs=0.0001)
    assert "cents per transaction" in c["definitions"]["average_basket_cents"]
    assert sum(r["current_sales_cents"] for r in c["category_mix"]) == 797088
    assert sum(r["previous_sales_cents"] for r in c["category_mix"]) == 700688
    assert len(c["largest_product_sales_changes"]) == 5
    assert m["issues"]["low_feedback_topics"] == [{"topic": "stock", "count": 1}]


@pytest.mark.asyncio
async def test_labor_comparison_requires_prior_actual_attendance(fake_backend):
    fake_backend.worked_shifts = [
        r for r in fake_backend.worked_shifts if r["business_date"] != "2026-10-01"
    ]
    result = await reports.get_end_of_day_metrics(tool_context=manager())
    assert result["code"] == "incomplete_report"
    assert "worked attendance for 2026-10-01" in result["missing_sources"]


def test_zero_denominators_are_unknown_ratios_not_fake_growth():
    from agents.cymbal_store_ops.reports.metrics import commercial_metrics

    empty = {"sales_cents": 0, "visitors": 0, "transactions": 0, "units": 0, "paid_minutes": 0}
    result = commercial_metrics(
        {"current": empty, "previous": empty, "business_date": "2026-10-02", "hourly": []},
        {"category_sales": [], "product_changes": []},
    )
    assert all(r["current"] is None and r["change_pct"] is None for r in result["ratios"].values())
    assert "sales_change_bridge" not in result


@pytest.mark.asyncio
async def test_public_report_projection_retains_evidence_and_renderer_keeps_full_data(fake_backend, monkeypatch):
    public = (await reports.get_end_of_day_metrics(tool_context=manager()))["rows"][0]
    full = (await reports._read_metrics(tool_context=manager()))["rows"][0]
    assert public["metrics_digest"] == full["metrics_digest"]
    assert len(full["hourly"]) == 24 and len(full["staff"]) == 8
    assert "hourly" not in public and "staff" not in public and "store" not in public
    assert len(json.dumps(public)) < len(json.dumps(full)) * .8
    peaks = public["commercial"]
    assert peaks["peak_transactions"]["local_hour"] == "1:00 PM"
    assert (peaks["peak_transactions"]["transactions"], peaks["peak_transactions"]["visitors"]) == (20, 52)
    assert peaks["peak_conversion"]["local_hour"] == "10:00 AM"
    assert (peaks["peak_conversion"]["transactions"], peaks["peak_conversion"]["visitors"]) == (16, 37)
    assert peaks["peak_conversion"]["conversion_pct"] == pytest.approx(16 / 37 * 100, abs=.0001)
    captured = []
    from agents.cymbal_store_ops.reports import render
    async def capture(metrics, prose):
        captured.append(metrics)
        raise RuntimeError("Stop after verifying renderer input")
    monkeypatch.setattr(render, "render_pdf", capture)
    result = await reports.create_end_of_day_dashboard(
        public["business_date"], public["metrics_digest"], "A steady day", "Review the trading day.", [], [], ACTIONS, manager()
    )
    assert result["code"] == "render_error"
    assert captured == [full]


def test_commercial_hourly_peaks_use_current_date_and_correct_denominator():
    from agents.cymbal_store_ops.reports.metrics import commercial_metrics
    empty = {"sales_cents": 0, "visitors": 0, "transactions": 0, "units": 0, "paid_minutes": 0}
    rows = [
        {"business_date": "2026-10-02", "hour": 11, "transactions": 20, "visitors": 100},
        {"business_date": "2026-10-02", "hour": 12, "transactions": 8, "visitors": 10},
        {"business_date": "2026-10-02", "hour": 13, "transactions": 0, "visitors": 0},
        {"business_date": "2026-10-01", "hour": 10, "transactions": 100, "visitors": 100},
    ]
    result = commercial_metrics(
        {"current": empty, "previous": empty, "business_date": "2026-10-02", "hourly": rows},
        {"category_sales": [], "product_changes": []},
    )
    assert result["peak_transactions"]["local_hour"] == "11:00 AM"
    assert result["peak_conversion"]["local_hour"] == "12:00 PM"
    assert result["peak_conversion"]["conversion_pct"] == 80


@pytest.mark.skipif(os.environ.get("RUN_PDF_RENDER_TESTS") != "1", reason="Explicit Chromium render check")
@pytest.mark.asyncio
@pytest.mark.parametrize("unbroken", [False, True])
async def test_maximum_accepted_prose_fits_one_a4_without_overflow(fake_backend, unbroken):
    from agents.cymbal_store_ops.reports.render import render_pdf, validate_pdf
    summary = "W" * 280 if unbroken else " ".join(["WWWWW"] * 44 + ["W" * 16])
    note = "W" * 145 if unbroken else " ".join(["WWWWW"] * 23 + ["W" * 7])
    prose = reports.narrative(summary, [note, note], [note, note])
    assert len(prose["summary"]) == 280 and len(prose["went_well"][0]) == 145
    full = (await reports._read_metrics(tool_context=manager()))["rows"][0]
    validate_pdf(await render_pdf(full, prose))
