"""A real ADK briefing finishes once, preserving state, traces and subsequent conversation."""
import json

import pytest
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.apps.app import ResumabilityConfig
from google.adk.runners import InMemoryRunner
from google.genai import types

from agents.cymbal_store_ops.chat_reply import ChatReplyPlugin
from agents.cymbal_store_ops.sub_agents.daily_briefing import (
    BriefingReply,
    make_daily_briefing_tool,
)
from agents.cymbal_store_ops.trace import ExecutionTracePlugin
from tests.unit.test_report_delivery import ACTIONS, IDENTITY, ScriptModel, clock_read, reply, run

PLAN = {"store_id": "S-014", "as_of": "2026-10-03T09:00:00-05:00", "summary": "Prioritize pickup commitments.",
        "items": [{"priority": 1, "area": "inventory", "headline": "Stage the reserved skincare",
                   "evidence": ["Four units are reserved across three orders.", "Priya already owns the replenishment task."]}],
        "next_actions": ACTIONS}


@pytest.mark.asyncio
@pytest.mark.parametrize("resumable,mixed", [(False, False), (True, False), (True, True)])
async def test_briefing_delivery_has_no_extra_synthesis_unless_other_reads_remain(fake_backend, resumable, mixed):
    calls = [types.Part(function_call=types.FunctionCall(name="daily_briefing", id="briefing-current",
                                                       args={"request": "Opening priorities; Priya is already assigned."}))]
    if mixed:
        calls.append(types.Part(function_call=types.FunctionCall(name="clock_read", id="clock-current")))
    draft = {"items": [{k: v for k, v in item.items() if k != "priority"} for item in PLAN["items"]], "next_actions": ACTIONS}
    responses = [calls, [types.Part(text=json.dumps(draft))]]
    if mixed:
        responses.append([reply("Combined results reviewed.")])
    responses.append([reply("I retained the earlier plan.")])
    model = ScriptModel(responses=responses)
    root = LlmAgent(name="store_manager_agent", model=model, tools=[make_daily_briefing_tool(model), clock_read])
    app = App(name="briefing_delivery", root_agent=root, plugins=[ExecutionTracePlugin(), ChatReplyPlugin()],
              resumability_config=ResumabilityConfig(is_resumable=resumable))
    runner = InMemoryRunner(app=app)
    try:
        session = await runner.session_service.create_session(app_name=app.name, user_id="manager", state=IDENTITY)
        events = await run(runner, session, "What matters this morning?")
        expected_calls = 3 if mixed else 2
        assert len(model.requests) == expected_calls
        assert len(model.requests[1].contents) == 1
        event = next(event for event in events if any(r.name == "daily_briefing" for r in event.get_function_responses()))
        result = next(r.response for r in event.get_function_responses() if r.name == "daily_briefing")
        assert result["reply_completed"] is (not mixed)
        assert bool(event.actions.skip_summarization) is (not mixed)
        saved = await runner.session_service.get_session(app_name=app.name, user_id="manager", session_id=session.id)
        assert BriefingReply.model_validate(saved.state["action_plan"]).model_dump()["items"] == result["items"]
        spans = [span for key, value in saved.state.items() if key.startswith("ui:trace:") and value
                 for span in value["spans"]]
        writer = next(span for span in spans if span["agent"] == "plan_writer" and span["kind"] == "model")
        assert writer["input"] == {"message_count": 1, "measurement": "after_agent_callback"}
        assert any(span["name"] == "get_inventory_context" and span["status"] == "ok" for span in spans)
        from frontend.server import sse
        serialized = [item.model_dump(mode="json", exclude_none=True) for item in events]
        async def stream():
            for item in serialized:
                yield item
        ui = [json.loads(frame.decode().removeprefix("data: ")) async for frame in sse(stream())]
        answers = [item["text"] for item in ui if item["type"] == "text"]
        assert len(answers) == 1
        if not mixed:
            assert "Four units are reserved across three orders." in answers[0]
            assert saved.state["ui:next_actions"] == ACTIONS
            assert answers[0].count("Stage the reserved skincare") == 1
            assert saved.state["action_plan"]["summary"] == "Stage the reserved skincare"
            assert saved.state["action_plan"]["store_id"] == IDENTITY["user:store_id"]
            assert saved.state["action_plan"]["as_of"] == "2026-10-03T09:00:00-05:00"
            assert saved.state["action_plan"]["items"][0]["suggested_task"] is None
        await run(runner, session, "Why did you prioritize that?")
        assert len(model.requests) == expected_calls + 1
        assert any(part.function_response and part.function_response.name == "daily_briefing"
                   for content in model.requests[-1].contents for part in content.parts or [])
    finally:
        await runner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [
    {"store_id": "S-014", "summary": "Incomplete output"},
    {"items": [], "next_actions": ACTIONS},
    {"items": [{"area": "inventory", "headline": "Read stock", "evidence": ["Seven units."]}],
     "next_actions": ACTIONS, "store_id": "S-ATTACKER", "as_of": "invented"},
])
async def test_invalid_writer_output_cannot_publish_a_previous_plan(fake_backend, invalid):
    model = ScriptModel(responses=[
        [types.Part(function_call=types.FunctionCall(name="daily_briefing", id="bad-briefing",
                                                   args={"request": "New opening priorities"}))],
        [types.Part(text=json.dumps(invalid))],
    ])
    root = LlmAgent(name="store_manager_agent", model=model, tools=[make_daily_briefing_tool(model)])
    runner = InMemoryRunner(app=App(name="briefing_failure", root_agent=root, plugins=[ChatReplyPlugin()]))
    events = []
    try:
        session = await runner.session_service.create_session(app_name="briefing_failure", user_id="manager",
                                                              state={**IDENTITY, "action_plan": PLAN})
        with pytest.raises(ValueError):
            async for event in runner.run_async(user_id="manager", session_id=session.id,
                    new_message=types.Content(role="user", parts=[types.Part(text="Refresh my opening priorities")])):
                events.append(event)
        assert not any(event.actions.skip_summarization for event in events)
        assert not any(event.actions.state_delta.get("ui:next_actions") for event in events)
        assert not any(part.text == "Prioritize pickup commitments." for event in events
                       for part in (event.content.parts if event.content else []) or [])
    finally:
        await runner.close()
