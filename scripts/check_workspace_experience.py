"""Verify real session ownership, private PDF delivery and optionally one live event analysis.

No model call is made unless --run-event is explicit. PDF validation uses an existing
review PDF saved through the actual ADK artifact service into this probe's own session.
Passwords are read from Secret Manager into memory only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import time
from collections import Counter
from pathlib import Path

from playwright.async_api import async_playwright


async def main(args):
    args.out.mkdir(parents=True, exist_ok=True)
    result = {"url": args.url, "checks": {}, "browser_errors": [], "model_calls_requested": 0}
    password = ""
    if args.secret:
        password = subprocess.run(
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
            check=True,
            timeout=45,
        ).stdout.strip()
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chromium")
        context = await browser.new_context(viewport={"width": 1440, "height": 1100})
        page = await context.new_page()
        page.set_default_timeout(45000)
        page.on("pageerror", lambda error: result["browser_errors"].append(str(error)))

        async def open_browser(ctx):
            tab = await ctx.new_page()
            await tab.goto(args.url)
            if password:
                response = await ctx.request.post(
                    args.url + "/api/login", data={"password": password}
                )
                assert response.status == 200
                await tab.reload()
            await tab.wait_for_selector("#scenarios button")
            return tab

        try:
            await page.close()
            page = await open_browser(context)
            page.on("pageerror", lambda error: result["browser_errors"].append(str(error)))
            await page.evaluate("newSession('Workspace review')")
            sid = await page.evaluate("session")
            await page.evaluate("refreshHistory()")
            await page.locator(".history summary").click()
            await page.get_by_role("button", name="Workspace review", exact=True).click()
            await page.wait_for_function("!busy")
            assert await page.evaluate("sessionState['user:role']") == "store_manager"
            assert await page.evaluate("session") == sid
            result["checks"]["history_restore"] = True

            foreign = await browser.new_context()
            other = await open_browser(foreign)
            denied = await foreign.request.get(args.url + f"/api/sessions/{sid}")
            assert denied.status == 404, await denied.text()
            result["checks"]["other_browser_denied"] = denied.status

            if args.pdf:
                from google.adk.artifacts import GcsArtifactService
                from google.genai import types

                cookie = next(
                    c["value"] for c in await context.cookies() if c["name"] == "cymbal_browser"
                )
                owner = "browser-" + cookie.partition(".")[0] + "-manager"
                service = GcsArtifactService(bucket_name=args.artifact_bucket)
                filename = "workspace-review.pdf"
                content = args.pdf.read_bytes()
                version = await service.save_artifact(
                    app_name="cymbal_store_ops",
                    user_id=owner,
                    session_id=sid,
                    filename=filename,
                    artifact=types.Part.from_bytes(data=content, mime_type="application/pdf"),
                    custom_metadata={"store_id": "S-014", "source": "existing review PDF"},
                )
                item = {"filename": filename, "version": version}
                listing = await context.request.get(args.url + f"/api/sessions/{sid}/artifacts")
                assert (
                    listing.status == 200
                    and item.items() <= (await listing.json())["artifacts"][0].items()
                )
                await page.evaluate("item => receiveArtifact(item)", item)
                await page.get_by_role("button", name="View report", exact=True).click()
                await page.wait_for_function("document.querySelector('#artifact-dialog').open")
                pdf_url = await page.locator("#artifact-frame").get_attribute("src")
                downloaded = await context.request.get(args.url + pdf_url)
                assert downloaded.status == 200 and await downloaded.body() == content
                assert downloaded.headers["content-type"] == "application/pdf"
                assert (await foreign.request.get(args.url + pdf_url)).status == 404
                # The PDF viewer in the dialog has its own download button; the app adds none.
                assert await page.locator("#artifact-download").count() == 0
                await page.screenshot(path=str(args.out / "pdf-preview.png"), full_page=True)
                await page.keyboard.press("Escape")
                assert not await page.locator("#artifact-dialog").evaluate("e => e.open")
                result["checks"]["pdf"] = {
                    "bytes": len(content),
                    "version": version,
                    "owned_delivery": True,
                    "foreign_denied": True,
                    "preview_modal": True,
                    "download": True,
                    "source": "Existing review PDF saved through real GcsArtifactService; no model generation in this check",
                }

            await page.evaluate("refreshNotifications()")
            notifications = await context.request.get(args.url + "/api/notifications")
            assert notifications.status == 200
            assert await page.locator("#notifications-open").is_visible()
            if args.run_event:
                result["model_calls_requested"] = 1
                await page.locator("#notifications-open").click()
                async with page.expect_response(
                    lambda r: r.url.endswith("/api/events") and r.request.method == "POST"
                ) as response:
                    await page.locator("#trigger-event").click()
                response = await response.value
                assert response.status == 202, await response.text()
                job_id = (await response.json())["job_id"]
                started = time.monotonic()
                while time.monotonic() - started < args.timeout:
                    rows = await context.request.get(args.url + "/api/notifications")
                    notification = next(
                        n for n in (await rows.json())["notifications"] if n["job_id"] == job_id
                    )
                    if notification["status"] in {"completed", "failed"}:
                        break
                    await asyncio.sleep(4)
                else:
                    raise TimeoutError("Event analysis exceeded deadline; no retry submitted")
                result["event"] = notification | {"seconds": round(time.monotonic() - started, 2)}
                assert notification["status"] == "completed", notification
                await page.evaluate("refreshNotifications()")
                await page.get_by_role("button", name="Open conversation", exact=True).click()
                await page.wait_for_function(
                    "!busy && !document.querySelector('#notifications-dialog').open"
                )
                assert await page.evaluate("session") == notification["analysis_session_id"]
                assert await page.locator(".msg.agent").count() == 1
                assert "Store event" in await page.locator("#log").inner_text()
                assert 3 <= await page.locator("#guide button").count() <= 5
                trace = await page.evaluate("[...traceState.spans.values()]")
                assert any(s["kind"] == "model" for s in trace), (
                    "No actual model execution trace restored"
                )
                (args.out / "event-trace.json").write_text(json.dumps(trace, indent=2))
                history = await context.request.get(
                    args.url + f"/api/sessions/{notification['analysis_session_id']}"
                )
                saved_history = await history.json()
                (args.out / "event-history.json").write_text(json.dumps(saved_history, indent=2))
                calls = Counter(
                    event["name"]
                    for event in saved_history["events"]
                    if event["type"] == "tool_call"
                )
                traced = Counter(span["name"] for span in trace if span["kind"] == "tool")
                assert all(traced[name] >= count for name, count in calls.items()), (
                    "Actual tool calls missing from restored trace"
                )
                result["event"]["trace_spans"] = len(trace)
                result["event"]["actual_tool_calls"] = dict(calls)
                result["event"]["source_review"] = (
                    "Compare saved tool responses and per-order slack with the actual answer; no forced tool route"
                )

                assert (
                    await foreign.request.get(
                        args.url + f"/api/sessions/{notification['analysis_session_id']}"
                    )
                ).status == 404
                await page.screenshot(path=str(args.out / "event-conversation.png"), full_page=True)

            await page.locator("#role").select_option("associate")
            await page.wait_for_function("session === null")
            assert await page.locator("#notifications-open").is_hidden()
            assert (
                await context.request.get(args.url + f"/api/sessions/{sid}?persona=associate")
            ).status == 404
            await page.evaluate("newSession('Associate workspace review')")
            assert await page.evaluate("sessionState['user:role']") == "associate"
            result["checks"]["persona_isolation"] = True
            await page.screenshot(path=str(args.out / "associate.png"), full_page=True)
            assert not result["browser_errors"]
            result["status"] = "passed"
            await other.close()
        except Exception as exc:
            result["status"] = "failed"
            result["error"] = f"{type(exc).__name__}: {exc}"
            await page.screenshot(path=str(args.out / "failure.png"), full_page=True)
            raise
        finally:
            (args.out / "report.json").write_text(json.dumps(result, indent=2))
            print(json.dumps(result, indent=2), flush=True)
            await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8084")
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", ""))
    parser.add_argument("--secret")
    parser.add_argument("--artifact-bucket", default=os.getenv("CYMBAL_ARTIFACT_BUCKET", ""))
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--run-event", action="store_true")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--out", type=Path, default=Path("build/tablet-review/workspace-complete"))
    asyncio.run(main(parser.parse_args()))
