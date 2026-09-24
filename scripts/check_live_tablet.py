"""Verify the deployed tablet chat, generated actions and actual ADK trace.

Credentials stay in memory. The probe follows one generated read-only suggestion (or an explicit --follow-up);
it never approves or cancels a store task. Each model request has a 180-second
deadline, with partial evidence saved on failure and no automatic retry.

Run only after the deployment is ready:
  /tmp/cymbal-ui-audit-venv/bin/python scripts/check_live_tablet.py --run-live
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import TimeoutError as BrowserTimeout
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "https://cymbal-frontend-demo-dev-763419985448.us-central1.run.app"


def save_report(path, report):
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o600)


async def wait_for_turn(page, label, timeout):
    started = time.monotonic()
    while True:
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError(
                f"{label} exceeded the {timeout}-second model deadline; no retry sent"
            )
        try:
            await page.wait_for_function(
                "!document.querySelector('#send').disabled", timeout=min(30000, remaining * 1000)
            )
            break
        except BrowserTimeout:
            print(f"{label}: waiting ({round(time.monotonic() - started)} seconds)", flush=True)
    if not await page.locator("#request-error").is_hidden():
        details = await page.locator("#stream .err").all_text_contents()
        raise RuntimeError(
            f"{label}: {details[-1] if details else 'the application reported a request failure'}"
        )
    return round(time.monotonic() - started, 2)


async def read_trace(page):
    return await page.evaluate(
        "({question:traceState.question, root_invocation_id:traceState.rootInvocationId, receiving:traceState.receiving, failed:traceState.failed, spans:[...traceState.spans.values()]})"
    )


async def probe(args):
    args.out.mkdir(parents=True, exist_ok=True)
    report = {
        "url": args.url,
        "status": "running",
        "checks": {},
        "turns": [],
        "chat_requests": [],
        "browser_errors": [],
    }
    password = ""
    authenticated = False
    browser = page = playwright = None
    stream_captures = []
    try:
        result = subprocess.run(
            [
                "gcloud",
                "secrets",
                "versions",
                "access",
                "latest",
                "--secret",
                args.secret,
                "--project",
                args.project,
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=True,
        )
        password = result.stdout.strip()
        if not password:
            raise RuntimeError("Secret Manager returned an empty deployment password")
        result = None
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 1100})
        response = await context.request.get(args.url + "/api/scenarios", timeout=30000)
        assert response.status == 401, "Scenario API must reject an unauthenticated browser"
        report["checks"]["password_gate"] = "pass"
        page = await context.new_page()
        page.set_default_timeout(30000)
        page.on(
            "pageerror",
            lambda error: report["browser_errors"].append(
                str(error).replace(password, "[redacted]") if password else str(error)
            ),
        )

        def capture_request(request):
            # Never record login bodies, cookies, authorization headers or storage state.
            if request.method == "POST" and urlparse(request.url).path == "/api/chat":
                body = request.post_data_json
                report["chat_requests"].append(
                    {"text": body.get("text"), "time_monotonic": time.monotonic()}
                )

        page.on("request", capture_request)

        async def capture_stream(response, number):
            try:
                payload = await response.body()
                file = args.out / f"chat-{number:02d}.sse"
                file.write_bytes(payload)
                file.chmod(0o600)
                report.setdefault("stream_artifacts", []).append(
                    {"file": str(file), "http_status": response.status, "bytes": len(payload)}
                )
            except Exception as error:
                report.setdefault("stream_capture_errors", []).append(
                    {"type": type(error).__name__, "message": str(error)}
                )

        def observe_response(response):
            if urlparse(response.url).path == "/api/chat":
                stream_captures.append(
                    asyncio.create_task(capture_stream(response, len(report["chat_requests"])))
                )

        page.on("response", observe_response)
        await page.goto(args.url, wait_until="domcontentloaded")
        await page.locator("#gate").wait_for(state="visible")
        await page.locator("#gate-pw").fill(password)
        await page.locator("#gate-form button").click()
        await page.locator(".welcome").wait_for()
        password = ""
        authenticated = True
        assert await page.locator("#gate").is_hidden()
        assert await page.locator("#gate-pw").input_value() == ""
        assert await page.locator("#role").input_value() == "manager"
        manager_scenarios = await page.locator("#scenarios button").all_inner_texts()
        assert len(manager_scenarios) == 6
        assert await page.locator("#guide button").count() == 3
        report["checks"]["manager_scenarios"] = manager_scenarios
        await page.screenshot(path=str(args.out / "manager-welcome.png"))

        before_requests = len(report["chat_requests"])
        before_answers = await page.locator(".msg.agent").count()
        print("Live opening request started.", flush=True)
        await page.locator("#text").fill(
            "Morning. What should I prioritize as we open the store today?"
        )
        await page.locator("#send").click()
        elapsed = await wait_for_turn(page, "Opening", args.timeout)
        assert len(report["chat_requests"]) - before_requests == 1, (
            "Opening produced duplicate HTTP requests"
        )
        assert await page.locator(".msg.agent").count() - before_answers == 1, (
            "Opening produced duplicate visible answers"
        )
        answer = await page.locator(".msg.agent").last.inner_text()
        suggestions = await page.locator("#guide button").evaluate_all(
            "els => els.map(el => ({label:el.textContent,prompt:el.title}))"
        )
        generated = await page.evaluate("nextActions")
        assert 3 <= len(suggestions) <= 5 and len(generated) == len(suggestions)
        assert [item["prompt"] for item in suggestions] == [item["prompt"] for item in generated]
        assert "ui:next_actions" not in await page.locator("#state").text_content()
        report["turns"].append(
            {
                "name": "opening",
                "elapsed_seconds": elapsed,
                "answer": answer,
                "suggestions": suggestions,
            }
        )
        await page.screenshot(path=str(args.out / "manager-opening.png"))

        trace = await read_trace(page)
        save_report(args.out / "opening-trace.json", trace)
        spans = trace["spans"]
        assert spans and not trace["receiving"] and not trace["failed"]
        by_id = {span["id"]: span for span in spans}
        for name in (
            "daily_briefing",
            "signals",
            "briefing_inventory",
            "briefing_coverage",
            "briefing_shrink",
            "plan_writer",
        ):
            found = [span for span in spans if span["name"] == name and span["kind"] == "agent"]
            assert found, f"Opening trace is missing the actual {name} agent span"
            assert all(
                isinstance(span.get("duration_ms"), (int, float)) and span["duration_ms"] >= 0
                for span in found
            ), f"Missing measured duration for {name}"
        assert any(span["name"] == "daily_briefing" and span["kind"] == "tool" for span in spans)
        assert any(span["kind"] == "model" for span in spans)
        assert len({span["invocation_id"] for span in spans}) >= 2, (
            "Nested briefing invocation not captured"
        )
        assert all(span.get("root_invocation_id") == trace["root_invocation_id"] for span in spans)
        assert all(not span.get("parent_id") or span["parent_id"] in by_id for span in spans), (
            "Trace contains an unresolved parent span"
        )
        inventory = next(
            (
                span
                for span in spans
                if span["name"] == "get_inventory_context" and span["kind"] == "tool"
            ),
            None,
        )
        assert (
            inventory is not None
            and inventory.get("input") is not None
            and inventory.get("output") is not None
        )
        assert isinstance(inventory.get("duration_ms"), (int, float))
        await page.locator("#activity-toggle").click()
        await page.locator("#view-trace").click()
        assert await page.locator(".trace-span").count() == len(spans)
        await page.screenshot(path=str(args.out / "opening-adk-trace.png"))
        row = page.locator(f'[data-span="{inventory["id"]}"]')
        await row.locator("summary").click()
        input_text, output_text = await row.locator("pre").all_inner_texts()
        assert (
            input_text if isinstance(inventory["input"], str) else json.loads(input_text)
        ) == inventory["input"]
        assert (
            output_text if isinstance(inventory["output"], str) else json.loads(output_text)
        ) == inventory["output"]
        await page.screenshot(path=str(args.out / "opening-inventory-trace.png"))
        await page.keyboard.press("Escape")
        assert await page.locator("#view-trace").evaluate("el => el === document.activeElement")
        await page.locator("#activity-close").click()
        report["checks"]["actual_nested_trace"] = {
            "spans": len(spans),
            "invocations": len({span["invocation_id"] for span in spans}),
            "inventory_duration_ms": inventory["duration_ms"],
        }

        if args.opening_only:
            plan = await page.evaluate("sessionState.action_plan")
            assert plan and 1 <= len(plan["items"]) <= 3
            assert [item["priority"] for item in plan["items"]] == list(
                range(1, len(plan["items"]) + 1)
            )
            assert plan["summary"] == plan["items"][0]["headline"]
            assert answer.count(plan["summary"]) == 1, "Legacy summary was displayed twice"
            assert all(not item.get("suggested_task") for item in plan["items"])
            writers = [
                span
                for span in spans
                if span["kind"] == "model" and span.get("agent") == "plan_writer"
            ]
            assert len(writers) == 1, "Expected one actual writer synthesis"
            report["checks"]["writer"] = {
                "duration_ms": writers[0]["duration_ms"],
                "output": writers[0].get("output"),
            }
            report["checks"]["canonical_plan"] = plan
            report["checks"]["facts_review"] = (
                "Pending manual comparison with saved actual source responses"
            )
            assert not report["browser_errors"]
            if stream_captures:
                await asyncio.wait_for(asyncio.gather(*stream_captures), timeout=5)
            report["status"] = "passed"
            save_report(args.out / "report.json", report)
            print(
                json.dumps(
                    {
                        "status": "passed",
                        "chat_requests": 1,
                        "seconds": elapsed,
                        "writer_ms": writers[0]["duration_ms"],
                        "report": str(args.out / "report.json"),
                    }
                ),
                flush=True,
            )
            return 0

        # a write chip is an imperative: the verb opens the prompt. The same words as nouns mid-sentence ("the pickup
        # schedule", "the inspection record") do not make a question a write.
        writes = re.compile(
            r"^\s*(create|assign|delegate|complete|mark|report|raise|schedule|approve|cancel|update|record|submit|send|move|direct|open|ask)\b",
            re.I,
        )
        reads = re.compile(
            r"^(show|review|read|verify|list|look|tell|walk|check|compare|explain|find|summari[sz]e|what|which|where|when|why|how|can|is|are|do)\b",
            re.I,
        )
        follow_index = next(
            (
                i
                for i, item in enumerate(suggestions)
                if reads.search(item["prompt"].strip()) and not writes.search(item["prompt"])
            ),
            None,
        )
        assert args.follow_up or follow_index is not None, (
            "No generated read-only suggestion available; provide --follow-up for an explicit read-only check"
        )
        before_requests = len(report["chat_requests"])
        before_answers = await page.locator(".msg.agent").count()
        if args.follow_up:
            follow_prompt = args.follow_up
            report["checks"]["follow_up_source"] = "explicit read-only test question"
            print("Sending the explicit read-only follow-up.", flush=True)
            await page.locator("#text").fill(follow_prompt)
            await page.locator("#send").click()
        else:
            follow_prompt = suggestions[follow_index]["prompt"]
            report["checks"]["follow_up_source"] = "generated suggestion"
            print("Following one generated read-only suggestion.", flush=True)
            await page.locator("#guide button").nth(follow_index).click()
        elapsed = await wait_for_turn(page, "Follow-up", args.timeout)
        assert len(report["chat_requests"]) - before_requests == 1
        assert await page.locator(".msg.agent").count() - before_answers == 1
        assert await page.locator(".confirm").count() == 0, (
            "Read-only follow-up unexpectedly requested a write"
        )
        assert 3 <= await page.locator("#guide button").count() <= 5
        follow_trace = await read_trace(page)
        assert (
            follow_trace["root_invocation_id"]
            and follow_trace["root_invocation_id"] != trace["root_invocation_id"]
        )
        assert not ({span["id"] for span in follow_trace["spans"]} & set(by_id)), (
            "Previous turn's spans leaked into follow-up"
        )
        report["turns"].append(
            {
                "name": "explicit_follow_up" if args.follow_up else "suggested_follow_up",
                "prompt": follow_prompt,
                "elapsed_seconds": elapsed,
                "answer": await page.locator(".msg.agent").last.inner_text(),
                "suggestions": await page.evaluate("nextActions"),
            }
        )
        save_report(args.out / "follow-up-trace.json", follow_trace)
        await page.screenshot(path=str(args.out / "manager-follow-up.png"))

        if args.inventory_snapshot:
            expected = json.loads(args.inventory_snapshot.read_text())
            expected = {row["product_id"]: row for row in expected}
            assert expected, "Independent inventory snapshot must not be empty"
            before_requests = len(report["chat_requests"])
            before_answers = await page.locator(".msg.agent").count()
            existing_reports = await page.evaluate("[...reportState.records.keys()]")
            print("Requesting complete inventory through the deployed agent.", flush=True)
            await page.locator("#text").fill(
                "Give me the complete store inventory, including product ID, name, category, on-hand units, shelf units and backroom units."
            )
            await page.locator("#send").click()
            elapsed = await wait_for_turn(page, "Complete inventory", args.timeout)
            assert len(report["chat_requests"]) - before_requests == 1
            assert await page.locator(".msg.agent").count() - before_answers == 1
            assert await page.locator(".confirm").count() == 0
            reports = await page.evaluate("[...reportState.records.values()]")
            new_reports = [item for item in reports if item["id"] not in existing_reports]
            assert len(new_reports) == 1, "Expected one new report from the actual agent"
            inventory_report = new_reports[0]
            actual = {row["product_id"]: row for row in inventory_report["rows"]}
            assert inventory_report["complete"] and inventory_report["total_matching"] == len(
                expected
            )
            assert len(inventory_report["rows"]) == len(actual) == len(expected)
            assert set(actual) == set(expected), "Report SKU set differs from independent data"
            quantity_fields = ("on_hand", "on_shelf_qty", "backroom_qty")
            for product_id, row in expected.items():
                for field in quantity_fields:
                    assert int(actual[product_id][field]) == int(row[field]), (
                        f"Report mismatch: {product_id}/{field}"
                    )
            save_report(args.out / "inventory-report.json", inventory_report)
            await page.locator(".report-card button").last.click()
            assert await page.locator("#report-table tbody tr").count() == min(50, len(expected))
            await page.locator("#report-search").fill("P-0101")
            assert await page.locator("#report-table tbody tr").count() == 1
            await page.screenshot(path=str(args.out / "inventory-report-search.png"))
            await page.locator("#report-search").fill("")
            async with page.expect_download() as download_info:
                await page.locator("#report-download").click()
            download = await download_info.value
            csv_path = args.out / "inventory.csv"
            await download.save_as(csv_path)
            csv_rows = list(csv.DictReader(io.StringIO(csv_path.read_text(encoding="utf-8-sig"))))
            assert len(csv_rows) == len(expected), "CSV omitted records"
            assert {row["product_id"] for row in csv_rows} == set(expected)
            for row in csv_rows:
                for field in quantity_fields:
                    assert int(row[field]) == int(expected[row["product_id"]][field])
            await page.keyboard.press("Escape")
            report["checks"]["complete_inventory"] = {
                "rows": len(actual),
                "quantity_cells_verified": len(actual) * 3,
                "csv": "pass",
                "search": "pass",
            }
            report["turns"].append(
                {
                    "name": "complete_inventory",
                    "elapsed_seconds": elapsed,
                    "answer": await page.locator(".msg.agent").last.inner_text(),
                    "suggestions": await page.evaluate("nextActions"),
                }
            )
            save_report(args.out / "inventory-trace.json", await read_trace(page))

        await page.select_option("#role", "associate")
        associate_scenarios = await page.locator("#scenarios button").all_inner_texts()
        assert len(associate_scenarios) == 3
        assert await page.locator("#conversation-title").inner_text() == "My shift"
        assert 3 <= await page.locator("#guide button").count() <= 5
        assert await page.locator(".msg.agent").count() == 0
        assert await page.evaluate("traceState.spans.size") == 0
        assert await page.evaluate("session") is None
        assert "Noor" not in await page.locator("#guide").inner_text()
        report["checks"]["associate_scenarios"] = associate_scenarios
        report["checks"]["associate_starters"] = await page.locator(
            "#guide button"
        ).all_inner_texts()
        await page.screenshot(path=str(args.out / "associate-welcome.png"))
        assert not report["browser_errors"], "Browser reported JavaScript errors"
        report["status"] = "passed"
        if stream_captures:
            await asyncio.wait_for(asyncio.gather(*stream_captures), timeout=5)
        await browser.close()
        browser = None
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error).replace(password, "[redacted]") if password else str(error)
        if page and authenticated:
            try:
                report["activity_errors"] = await page.locator("#stream .err").all_text_contents()
                report["elapsed_since_last_chat_seconds"] = (
                    round(time.monotonic() - report["chat_requests"][-1]["time_monotonic"], 2)
                    if report["chat_requests"]
                    else None
                )
                save_report(args.out / "partial-trace.json", await read_trace(page))
                await page.screenshot(path=str(args.out / "failure.png"))
            except Exception:
                pass  # Preserve the original failure if the browser has already disconnected.
        if stream_captures:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*stream_captures, return_exceptions=True), timeout=5
                )
            except TimeoutError:
                report["stream_capture_incomplete"] = True
        save_report(args.out / "report.json", report)
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": report["error"],
                    "report": str(args.out / "report.json"),
                }
            ),
            flush=True,
        )
        return 1
    finally:
        password = ""
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        if playwright:
            await playwright.stop()
    save_report(args.out / "report.json", report)
    print(
        json.dumps(
            {
                "status": "passed",
                "turn_seconds": [turn["elapsed_seconds"] for turn in report["turns"]],
                "chat_requests": len(report["chat_requests"]),
                "trace_spans": report["checks"]["actual_nested_trace"]["spans"],
                "report": str(args.out / "report.json"),
            }
        ),
        flush=True,
    )
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-live", action="store_true", help="Run only once the deployment is ready"
    )
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    parser.add_argument(
        "--secret",
        default=f"cymbal-frontend-{os.environ.get('WORKSHOP_NAMESPACE', 'demo')}-dev-password",
    )
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--opening-only",
        action="store_true",
        help="One opening request only; preserve source/latency evidence without a follow-up",
    )
    parser.add_argument(
        "--follow-up",
        help="Explicit read-only question for targeted source verification; generated chips are still inspected",
    )
    parser.add_argument(
        "--inventory-snapshot",
        type=Path,
        help="Independent store inventory JSON for a live full-report/CSV check",
    )
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "tablet-review" / "live")
    args = parser.parse_args()
    if not args.run_live:
        parser.error("Pass --run-live after deployment is ready; no network requests were sent")
    args.url = args.url.rstrip("/")
    return asyncio.run(probe(args))


if __name__ == "__main__":
    raise SystemExit(main())
