"""Pass an actual ADK trace fixture through server shaping and the browser modal.

The fixture comes from an InMemoryRunner with deterministic model/data adapters.
This is a transport/UI integration check, not a live engine latency measurement.
Run with the Playwright environment used for check_tablet_experience.py.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "tablet-review"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=ROOT / "build" / "trace-fixture.json")
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text())
    # Use the application's interpreter for real server shaping, while keeping
    # the browser dependency out of the deployed application environment.
    code = """
import json, sys
from frontend.server import shape
fixture = json.load(sys.stdin)
groups = {}
for span in fixture['spans']:
    groups.setdefault(span['agent'], []).append(span)
delta = {'ui:trace:' + author: {'invocation_id': spans[0]['invocation_id'],
         'root_invocation_id': fixture['root_invocation_id'], 'spans': spans}
         for author, spans in groups.items()}
print(json.dumps(shape({'author':'coordinator','actions':{'state_delta':delta}})))
"""
    shaped = subprocess.run([str(ROOT / ".venv/bin/python"), "-c", code], input=json.dumps(fixture),
                            capture_output=True, text=True, cwd=ROOT, check=True)
    events = json.loads(shaped.stdout)
    assert all(event["type"] == "trace" for event in events)
    spans = [span for event in events for span in event["spans"]]
    assert len(spans) == len(fixture["spans"])
    assert {span["id"] for span in spans} == {span["id"] for span in fixture["spans"]}
    for original in fixture["spans"]:
        actual = next(span for span in spans if span["id"] == original["id"])
        for field in ("parent_id", "start_ms", "duration_ms", "invocation_id", "root_invocation_id"):
            assert actual.get(field) == original.get(field)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "adk-trace-transport.json").write_text(json.dumps(events, indent=2) + "\n")
    errors, calls = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1440})
        page.on("pageerror", lambda error: errors.append(str(error)))

        def route(request):
            path = request.request.url.split("localhost:8773")[-1]
            if path == "/api/config":
                request.fulfill(json={"password_required": False, "signed_in": True, "target": {"kind": "ADK-fixture-test"}})
            elif path == "/api/scenarios":
                request.fulfill(json=yaml.safe_load((ROOT / "frontend/scenarios.yaml").read_text()))
            elif path == "/api/sessions":
                request.fulfill(json={"session_id": "fixture-test", "state": {}})
            elif path == "/api/chat":
                calls.append(request.request.post_data_json)
                stream = events + [{"type": "text", "text": "Fixture run completed.", "partial": False}, {"type": "done"}]
                request.fulfill(content_type="text/event-stream", body="".join("data: " + json.dumps(event) + "\n\n" for event in stream))
            else:
                file = ROOT / "frontend/static" / ("index.html" if path == "/" else path.removeprefix("/static/"))
                if file.is_file():
                    request.fulfill(path=file, content_type={".js": "application/javascript", ".css": "text/css", ".html": "text/html"}.get(file.suffix, "text/plain"))
                else:
                    request.fulfill(status=404)

        page.route("http://localhost:8773/**", route)
        page.goto("http://localhost:8773/")
        page.locator("#text").fill("Opening priorities")
        page.locator("#send").click()
        page.wait_for_selector(".msg.agent")
        assert len(calls) == 1
        page.locator("#activity-toggle").click()
        page.locator("#view-trace").click()
        assert page.locator(".trace-span").count() == len(spans)
        rows = page.evaluate("traceRows().map(({span,depth}) => ({id:span.id,parent:span.parent_id,depth,duration:span.duration_ms,start:span.start_ms,name:span.name}))")
        by_id = {row["id"]: row for row in rows}
        for original in spans:
            row = by_id[original["id"]]
            assert row["duration"] == original["duration_ms"] and row["start"] == original["start_ms"]
            if original.get("parent_id") in by_id:
                assert row["depth"] == by_id[original["parent_id"]]["depth"] + 1
        for name in ("daily_briefing", "signals", "briefing_inventory", "briefing_coverage", "briefing_shrink", "get_inventory_context"):
            assert any(row["name"] == name for row in rows), name
        assert len({span["invocation_id"] for span in spans}) > 1
        assert page.evaluate("traceState.rootInvocationId") == fixture["root_invocation_id"]
        page.screenshot(path=str(OUT / "adk-trace-runner-overview.png"), full_page=True)
        context = next(span for span in spans if span["name"] == "get_inventory_context")
        row = page.locator(f'[data-span="{context["id"]}"]')
        row.locator("summary").click()
        actual_input = json.loads(row.locator("pre").first.inner_text())
        actual_output = json.loads(row.locator("pre").last.inner_text())
        assert actual_input == context["input"] and actual_output == context["output"]
        page.screenshot(path=str(OUT / "adk-trace-runner-inventory.png"), full_page=True)
        page.locator("#trace-close").focus()
        page.keyboard.press("Shift+Tab")
        assert page.locator("#trace-dialog").evaluate("el => el.contains(document.activeElement)")
        page.keyboard.press("Escape")
        assert page.locator("#view-trace").evaluate("el => el === document.activeElement")
        assert not errors, errors
        browser.close()
    report = {"source": str(args.fixture), "source_type": "InMemoryRunner with deterministic model and data adapters",
              "spans": len(spans), "nested_invocations": len({span["invocation_id"] for span in spans}),
              "server_transport": "pass", "parent_hierarchy": "pass", "captured_timings_preserved": "pass",
              "inventory_input_output": "pass", "keyboard_focus": "pass", "browser_errors": errors}
    (OUT / "adk-trace-integration.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
