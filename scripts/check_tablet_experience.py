"""Browser checks of persona/scenario links, suggested activities, activity visibility and tablet layout.

Uses a deterministic API response to isolate the browser from live model timing. Screenshots are UI fixtures.
"""
import json
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "tablet-review"
OUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1366, "height": 1024}, device_scale_factor=1)
    requests = []
    errors = []
    response_mode = {"value": "success"}
    confirmations = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    def route(request):
        path = request.request.url.split("localhost:8772")[-1]
        if path == "/api/config":
            request.fulfill(json={"password_required": False, "signed_in": True, "target": {"kind": "browser-test"}})
        elif path == "/api/scenarios":
            request.fulfill(json=yaml.safe_load((ROOT / "frontend/scenarios.yaml").read_text()))
        elif path == "/api/sessions":
            request.fulfill(json={"session_id": "ui-test", "state": {}})
        elif path == "/api/confirm":
            confirmations.append(request.request.post_data_json)
            events = [{"type": "text", "author": "store_tasks", "text": "Cancelled. No task was changed.", "partial": False}, {"type": "done"}]
            request.fulfill(content_type="text/event-stream", body="".join("data: " + json.dumps(e) + "\n\n" for e in events))
        elif path == "/api/chat":
            requests.append(request.request.post_data_json)
            if response_mode["value"] == "error":
                request.fulfill(content_type="text/event-stream", body='data: {"type":"error","message":"Engine unavailable"}\n\ndata: {"type":"done"}\n\n')
                return
            if response_mode["value"] == "confirmation":
                events = [{"type": "confirmation", "tool": "create_store_task", "fc_id": "cancel-test", "invocation_id": "cancel-inv", "hint": "Create the task?", "args": {"note": "Review stock"}}, {"type": "done"}]
                request.fulfill(content_type="text/event-stream", body="".join("data: " + json.dumps(e) + "\n\n" for e in events))
                return
            if response_mode["value"] == "terminal_error":
                events = [{"type": "text", "author": "store_tasks", "text": "The task could not be updated.", "partial": False}, {"type": "done"}]
                request.fulfill(content_type="text/event-stream", body="".join("data: " + json.dumps(e) + "\n\n" for e in events))
                return
            events = [
                {"type": "tool_call", "name": "get_stock_location", "author": "inventory_excellence", "call_id": "t1", "args": {"product_id": "P-0101"}},
                {"type": "tool_result", "name": "get_stock_location", "author": "inventory_excellence", "call_id": "t1", "data": {"status": "SUCCESS", "rows": []}},
                {"type": "agent_note", "author": "inventory_excellence", "text": "Specialist working result", "partial": False},
                {"type": "trace", "source": "ui:trace:briefing", "root_invocation_id": "outer", "spans": [
                    {"id": "root-span", "agent": "store_manager_agent", "name": "store_manager_agent", "kind": "agent", "start_ms": 1000, "duration_ms": 1200, "status": "ok", "invocation_id": "outer"},
                    {"id": "briefing-call", "parent_id": "root-span", "agent": "store_manager_agent", "name": "daily_briefing", "kind": "tool", "start_ms": 1100, "duration_ms": 1000, "status": "ok", "invocation_id": "outer"},
                    {"id": "signals", "parent_id": "briefing-call", "agent": "signals", "name": "signals", "kind": "agent", "start_ms": 1200, "duration_ms": 700, "status": "ok", "invocation_id": "nested"},
                    {"id": "inventory-span", "parent_id": "signals", "agent": "briefing_inventory", "name": "briefing_inventory", "kind": "agent", "start_ms": 1210, "duration_ms": 500, "status": "ok", "invocation_id": "nested"},
                    {"id": "stock-span", "parent_id": "inventory-span", "agent": "briefing_inventory", "name": "get_osa_exceptions", "kind": "tool", "start_ms": 1300, "duration_ms": 300, "status": "ok", "invocation_id": "nested", "input": {"limit": 2}, "output": {"product": "Hydra Cream", "note": "<img src=x onerror=alert(1)>"}},
                    {"id": "plan-span", "parent_id": "briefing-call", "agent": "plan_writer", "name": "plan_writer", "kind": "agent", "start_ms": 1900, "duration_ms": 100, "status": "ok", "invocation_id": "nested"},
                    {"id": "model-span", "parent_id": "plan-span", "agent": "plan_writer", "name": "gemini", "kind": "model", "start_ms": 1910, "duration_ms": 80, "status": "ok", "invocation_id": "nested", "output": {"tool_names": [], "usage": {"total_tokens": 300}}},
                ]},
                {"type": "text", "author": "store_manager_agent", "text": "Use the skincare backstock in bay B2 for the Hydra Cream pickups. Four units cover the three orders; the first is due at 9:30 a.m.", "partial": False},
                {"type": "state", "delta": {"ui:next_actions": [
                    {"label": "Review pickup deadlines", "prompt": "Show the Lumière Hydra Cream pickup deadlines."},
                    {"label": "Check Priya’s work", "prompt": "What work is already assigned to Priya?"},
                    {"label": "Review incoming stock", "prompt": "When is the Lumière Hydra Cream replenishment expected?"}]}},
                {"type": "done"}]
            request.fulfill(content_type="text/event-stream", body="".join("data: " + json.dumps(e) + "\n\n" for e in events))
        else:
            file = ROOT / "frontend/static" / ("index.html" if path == "/" else path.removeprefix("/static/"))
            if file.is_file():
                request.fulfill(path=file, content_type={".js": "application/javascript", ".css": "text/css", ".html": "text/html"}.get(file.suffix, "text/plain"))
            else:
                request.fulfill(status=404)

    page.route("http://localhost:8772/**", route)
    page.goto("http://localhost:8772/")
    page.wait_for_selector("#guide button")
    assert page.locator("#scenarios button").count() == 5
    assert page.locator("#guide button").count() == 3
    # Each reset selects exactly two standard requests and one complex request from
    # the active scenario. Rendering does not re-roll them or change their scope.
    selection_checks = page.evaluate("""() => scenarios.map(scenario => {
      const first = selectStarterPrompts(scenario, () => 0);
      const other = selectStarterPrompts(scenario, () => 0.99);
      return {id: scenario.id, count: first.length,
        standard: first.filter(p => p.complexity === 'standard').length,
        complex: first.filter(p => p.complexity === 'complex').length,
        unique: new Set(first.map(p => p.say)).size,
        scoped: first.every(p => scenario.prompts.includes(p)),
        varied: JSON.stringify(first) !== JSON.stringify(other)};
    })""")
    assert all(check["count"] == check["unique"] == 3 and check["standard"] == 2
               and check["complex"] == 1 and check["scoped"] and check["varied"] for check in selection_checks)
    first_starters = page.locator("#guide button").all_inner_texts()
    page.evaluate("window.previousStarters = starterPrompts; drawPrompts(); drawPrompts();")
    assert page.locator("#guide button").all_inner_texts() == first_starters
    assert page.evaluate("starterPrompts === window.previousStarters")
    page.locator("#new-session").click()
    assert page.evaluate("starterPrompts !== window.previousStarters")
    assert page.locator("#guide button").count() == 3
    page.evaluate("window.previousStarters = starterPrompts")
    page.locator("#scenarios button").nth(1).click()
    assert page.evaluate("starterPrompts !== window.previousStarters && starterPrompts.every(p => active.prompts.includes(p))")
    assert page.evaluate("starterPrompts.map(p => p.complexity)") == ["standard", "standard", "complex"]
    assert page.locator("#guide button").first.bounding_box()["height"] >= 44
    page.locator("#activity-toggle").click()
    page.locator("#view-trace").click()
    assert page.locator("#trace-dialog").is_visible()
    assert "Send a message" in page.locator("#trace-status").inner_text()
    page.keyboard.press("Escape")
    assert not page.locator("#trace-dialog").is_visible()
    assert page.locator("#view-trace").evaluate("el => el === document.activeElement")
    page.locator("#activity-close").click()
    page.select_option("#role", "associate")
    assert page.locator("#scenarios button").count() == 3
    assert page.locator("#conversation-title").inner_text() == "My shift"
    assert "Noor" not in page.locator("#guide").inner_text()
    assert page.evaluate("active.sign_in === 'associate' && starterPrompts.every(p => active.prompts.includes(p))")
    page.select_option("#role", "manager")
    page.locator("#guide button").first.click()
    page.wait_for_selector(".msg.agent")
    assert len(requests) == 1 and page.locator(".msg.agent").count() == 1
    assert "Specialist working result" not in page.locator("#log").inner_text()
    assert page.locator("#guide button").count() == 3
    assert page.locator("#guide button").first.inner_text() == "Review pickup deadlines"
    assert "ui:next_actions" not in page.locator("#state").text_content()
    page.evaluate("sessionState['ui:trace:old'] = {spans:[{name:'old raw trace'}]}; renderState()")
    assert "ui:trace:" not in page.locator("#state").text_content()
    page.locator("#activity-toggle").click()
    assert "Tool call" in page.locator("#stream").inner_text()
    assert "Inventory excellence" in page.locator("#stream").inner_text()
    page.locator("#view-trace").click()
    assert page.locator(".trace-span").count() == 7
    assert "daily_briefing" in page.locator("#trace-spans").inner_text()
    assert "plan_writer" in page.locator("#trace-spans").inner_text()
    assert "1.20 s" in page.locator("#trace-status").inner_text()
    page.locator('[data-span="stock-span"] summary').click()
    assert '"limit": 2' in page.locator('[data-span="stock-span"] pre').first.inner_text()
    assert page.locator("#trace-spans img").count() == 0
    depth = page.locator('[data-span="stock-span"] .trace-operation').evaluate("el => parseInt(el.style.paddingLeft)")
    assert depth == 64
    # A completion snapshot updates the existing span rather than adding another row.
    page.evaluate("receiveTrace({spans:[{id:'stock-span',kind:'tool',duration_ms:350,status:'ok'}]})")
    page.wait_for_function("document.querySelector('[data-span=stock-span] .trace-duration').textContent === '350 ms'")
    assert page.locator(".trace-span").count() == 7
    assert page.locator('[data-span="stock-span"]').get_attribute("open") is not None
    page.evaluate("receiveTrace({root_invocation_id:'previous-turn',spans:[{id:'stale',kind:'tool',name:'stale lookup'}]})")
    assert page.locator(".trace-span").count() == 7
    page.screenshot(path=str(OUT / "adk-trace.png"), full_page=True)
    page.locator("#trace-close").click()
    # Concurrent instances of one tool must retain separate results and a real waiting status.
    page.evaluate("""() => {
      waitingEl = waiting();
      handle({type:'tool_call', name:'inventory_excellence', author:'store_manager_agent', call_id:'agent-live', args:{}});
      handle({type:'tool_call', name:'check_store_stock', author:'inventory_excellence', call_id:'stock-a', args:{}});
      handle({type:'tool_call', name:'check_store_stock', author:'inventory_excellence', call_id:'stock-b', args:{}});
    }""")
    assert page.locator(".thinking").inner_text() == "Checking stock and pickup demand…"
    page.evaluate("""() => {
      handle({type:'tool_result', name:'check_store_stock', call_id:'stock-b', data:{units:3}});
      handle({type:'tool_result', name:'check_store_stock', call_id:'stock-a', data:{units:7, updated_at:'2026-10-03T14:30:00Z'}});
      handle({type:'tool_result', name:'inventory_excellence', call_id:'agent-live', data:{result:'Ready'}});
    }""")
    assert page.locator(".thinking").inner_text() == "Preparing your answer…"
    assert page.locator(".call-status").count() == 0
    assert "9:30 AM CDT" in page.locator("#stream").text_content()
    assert "2026-10-03T14:30" not in page.locator("#stream").text_content()
    page.evaluate("waitingEl.remove(); waitingEl = null")
    page.locator("#activity-close").click()
    page.screenshot(path=str(OUT / "tablet.png"), full_page=True)
    page.locator("#expand").click()
    assert page.locator("#expand").bounding_box()["y"] < 50
    page.screenshot(path=str(OUT / "expanded.png"), full_page=True)
    for width, height in [(1024, 768), (820, 1180), (390, 844)]:
        page.set_viewport_size({"width": width, "height": height})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert page.locator("#send").bounding_box()["width"] >= 40
        assert page.locator("#expand").bounding_box()["y"] < 50
        page.locator("#activity-toggle").click()
        page.locator("#view-trace").click()
        bounds = page.locator("#trace-dialog").bounding_box()
        assert bounds["width"] <= width and bounds["height"] <= height
        assert page.locator("#trace-dialog").evaluate("el => el.scrollWidth <= el.clientWidth")
        page.keyboard.press("Escape")
        page.locator("#activity-close").click()
    page.set_viewport_size({"width": 1366, "height": 1024})
    page.locator("#expand").click()
    assert not page.locator("body").evaluate("el => el.classList.contains('expanded')")
    # One centered chip and five wrapped chips remain tappable.
    page.evaluate("nextActions = [{label:'Review pickup deadlines', prompt:'Show pickup deadlines'}]; drawPrompts()")
    chip = page.locator("#guide button").bounding_box()
    guide = page.locator("#guide").bounding_box()
    assert chip["width"] >= 240 and abs(chip["x"] + chip["width"] / 2 - guide["x"] - guide["width"] / 2) < 2
    page.evaluate("nextActions = Array.from({length:5}, (_,i) => ({label:'Review activity ' + i, prompt:'Show activity ' + i})); drawPrompts()")
    assert page.locator("#guide button").count() == 5
    assert all(box["height"] >= 44 for box in page.locator("#guide button").evaluate_all("els => els.map(el => ({height:el.getBoundingClientRect().height}))"))
    # Repeated submit in one event-loop turn must create one HTTP request. Failed turns remove stale actions.
    response_mode["value"] = "error"
    page.evaluate("document.querySelector('#text').value = 'Check again'; document.querySelector('#form').requestSubmit(); document.querySelector('#form').requestSubmit();")
    page.wait_for_selector("#request-error:not([hidden])")
    assert len(requests) == 2
    assert page.locator("#guide button").count() == 0
    assert page.locator(".msg.agent").count() == 1
    page.locator("#activity-toggle").click()
    page.locator("#view-trace").click()
    assert page.locator(".trace-span").count() == 0
    assert "No execution spans" in page.locator("#trace-status").inner_text()
    page.keyboard.press("Escape")
    page.locator("#activity-close").click()
    # Waiting states show no made-up calls or durations; a persona change clears them.
    page.evaluate("beginTrace('A pending question')")
    page.locator("#activity-toggle").click()
    page.locator("#view-trace").click()
    assert "Waiting for recorded execution spans" in page.locator("#trace-status").inner_text()
    assert page.locator(".trace-span").count() == 0
    page.keyboard.press("Escape")
    page.locator("#activity-close").click()
    page.select_option("#role", "associate")
    assert page.evaluate("traceState.spans.size") == 0
    assert page.evaluate("traceState.question") == ""
    # The confirmation's display is localized, while its raw action data remains unchanged.
    page.evaluate("""handle({type:'confirmation', tool:'create_store_task', fc_id:'review-1', invocation_id:'inv-1', hint:'Complete by 2026-10-03T09:30:00-05:00', args:{due_at:'2026-10-03T09:30:00-05:00', note:'<img src=x onerror=alert(1)>'}})""")
    assert "9:30 AM CDT" in page.locator(".confirm").inner_text()
    assert "2026-10-03T" not in page.locator(".confirm").inner_text()
    assert page.locator(".confirm img").count() == 0
    # A deterministic cancellation has no suggested actions. It must not revive
    # initial starter prompts as though they were generated follow-up activities.
    page.locator("#new-session").click()
    assert page.locator("#guide button").count() == 3
    response_mode["value"] = "confirmation"
    page.locator("#text").fill("Create the stock review task")
    page.locator("#send").click()
    page.wait_for_selector(".confirm")
    assert page.locator("#guide button").count() == 0
    page.locator(".confirm button").get_by_text("Cancel", exact=True).click()
    page.wait_for_function("document.querySelector('.confirmation-status').textContent === 'Cancellation sent.'")
    assert len(confirmations) == 1 and confirmations[0]["confirmed"] is False
    assert page.locator(".msg.agent").last.inner_text().endswith("Cancelled. No task was changed.")
    assert page.locator("#guide button").count() == 0
    assert page.evaluate("hasConversation") is True
    assert page.evaluate("nextActions") == []
    # The same contract applies to a plain terminal failure, not only SSE errors.
    page.locator("#new-session").click()
    assert page.locator("#guide button").count() == 3
    response_mode["value"] = "terminal_error"
    page.locator("#text").fill("Update the task")
    page.locator("#send").click()
    page.wait_for_selector(".msg.agent")
    assert page.locator("#guide button").count() == 0
    assert page.evaluate("hasConversation") is True
    assert not errors, errors
    browser.close()
print("Browser checks passed: persona/scenario links, 1/3/5 activity chips, one request and answer, stale-action removal, concurrent tool activity, tool-driven status, readable times, escaped confirmation, ADK trace hierarchy/timing/updates/empty states/keyboard/reset, tablet/expanded controls and three viewport sizes.")
