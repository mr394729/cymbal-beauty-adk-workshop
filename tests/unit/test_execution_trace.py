"""Trace transport uses real ADK runners/AgentTool nesting and contains no model reasoning."""
import asyncio
import json
import time
import uuid

import pytest
from google.adk.agents import BaseAgent, LlmAgent, ParallelAgent, SequentialAgent
from google.adk.apps import App
from google.adk.apps.app import ResumabilityConfig
from google.adk.events import Event
from google.adk.models import LlmResponse
from google.adk.models.base_llm import BaseLlm
from google.adk.runners import InMemoryRunner
from google.adk.tools import ToolContext
from google.adk.tools.agent_tool import AgentTool
from google.genai import types

from agents.cymbal_store_ops.sub_agents.briefing_signals import BriefingSignals
from agents.cymbal_store_ops.trace import ExecutionTracePlugin, bounded

MANAGER = {"user:user_id": "U-M014", "user:store_id": "S-014", "user:role": "store_manager"}


class TestModel(BaseLlm):
    __test__ = False
    model: str = "trace-test-model"

    async def generate_content_async(self, llm_request, stream=False):
        last_user = max((i for i, content in enumerate(llm_request.contents)
                         if content.role == "user" and any(part.text for part in content.parts or [])), default=-1)
        answered = any(part.function_response for content in llm_request.contents[last_user + 1:]
                       for part in content.parts or [])
        parts = ([types.Part(text="never disclose this hidden reasoning", thought=True), types.Part(text="Briefing complete.")]
                 if answered else [types.Part(function_call=types.FunctionCall(
                     name="daily_briefing", args={"request": "Opening priorities"}, id=str(uuid.uuid4())))])
        yield LlmResponse(content=types.Content(role="model", parts=parts),
                          usage_metadata=types.GenerateContentResponseUsageMetadata(
                              prompt_token_count=10, candidates_token_count=20, thoughts_token_count=7,
                              total_token_count=37))


class FinishBriefing(BaseAgent):
    async def _run_async_impl(self, ctx):
        inventory = json.loads(ctx.session.state["temp:briefing_inventory"])
        value = inventory["get_inventory_context"]["rows"][0]["decision"]["available_to_promise_units"]
        yield Event(author=self.name, invocation_id=ctx.invocation_id,
                    content=types.Content(role="model", parts=[types.Part(text=f"{value} units available")]))


def traced_runner():
    branches = [BriefingSignals(name=f"briefing_{area}", area=area, output_key=f"temp:briefing_{area}")
                for area in ("inventory", "coverage", "shrink")]
    child = SequentialAgent(name="daily_briefing", sub_agents=[
        ParallelAgent(name="signals", sub_agents=branches), FinishBriefing(name="plan_result")])
    root = LlmAgent(name="coordinator", model=TestModel(), tools=[AgentTool(child)])
    return InMemoryRunner(agent=root, app_name="trace_test", plugins=[ExecutionTracePlugin()])


async def collect(runner, session, message):
    return [event async for event in runner.run_async(user_id=session.user_id, session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=message)]))]


def spans(events):
    rows = {}
    for event in events:
        for key, snapshot in event.actions.state_delta.items():
            if key.startswith("ui:trace:") and snapshot:
                for span in snapshot["spans"]:
                    rows[span["id"]] = span
    return list(rows.values())


@pytest.mark.asyncio
async def test_nested_agenttool_transports_real_branch_tool_and_model_spans(fake_backend):
    runner = traced_runner()
    try:
        session = await runner.session_service.create_session(app_name="trace_test", user_id="manager", state=MANAGER)
        events = await collect(runner, session, "Opening priorities")
    finally:
        await runner.close()
    rows = spans(events)
    assert {row["kind"] for row in rows} == {"agent", "model", "tool"}
    agents = {row["name"]: row for row in rows if row["kind"] == "agent"}
    assert {"coordinator", "daily_briefing", "signals", "briefing_inventory", "briefing_coverage", "briefing_shrink"} <= agents.keys()
    outer_tool = next(row for row in rows if row["kind"] == "tool" and row["name"] == "daily_briefing")
    assert agents["daily_briefing"]["parent_id"] == outer_tool["id"]
    assert agents["signals"]["parent_id"] == agents["daily_briefing"]["id"]
    assert agents["briefing_inventory"]["parent_id"] == agents["signals"]["id"]
    assert len({row["root_invocation_id"] for row in rows}) == 1
    assert len({row["invocation_id"] for row in rows}) == 2
    inventory = next(row for row in rows if row["name"] == "get_inventory_context")
    assert inventory["agent"] == "briefing_inventory"
    assert inventory["parent_id"] == agents["briefing_inventory"]["id"]
    assert inventory["input"] == {"product_name": "P-0101"}
    assert inventory["status"] == "ok" and inventory["duration_ms"] > 0
    assert all(row["start_ms"] > 1_000_000_000_000 for row in rows)
    assert all(row["duration_ms"] is not None and row["duration_ms"] >= 0 for row in rows)
    assert all(row["status"] == "ok" for row in rows)
    assert "never disclose" not in json.dumps(rows)
    models = [row for row in rows if row["kind"] == "model"]
    assert len(models) == 2 and models[0]["output"]["usage"]["total_token_count"] == 37
    assert models[0]["output"]["usage"]["reasoning_token_count"] == 7


@pytest.mark.asyncio
async def test_shared_plugin_has_no_cross_session_trace_state(fake_backend):
    runner = traced_runner()
    try:
        sessions = [await runner.session_service.create_session(app_name="trace_test", user_id=user, state=MANAGER)
                    for user in ("first", "second")]
        first, second = await asyncio.gather(collect(runner, sessions[0], "First session marker"),
                                             collect(runner, sessions[1], "Second session marker"))
        left, right = spans(first), spans(second)
        assert {row["id"] for row in left}.isdisjoint(row["id"] for row in right)
        assert "Second session marker" not in json.dumps(left)
        assert "First session marker" not in json.dumps(right)
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_consecutive_turns_clear_old_groups_and_keep_only_current_root(fake_backend):
    runner = traced_runner()
    try:
        session = await runner.session_service.create_session(app_name="trace_test", user_id="manager", state=MANAGER)
        first = spans(await collect(runner, session, "First turn"))
        second = spans(await collect(runner, session, "Second turn"))
        assert {row["id"] for row in first}.isdisjoint(row["id"] for row in second)
        assert len({row["root_invocation_id"] for row in second}) == 1
        assert "First turn" not in json.dumps(second)
        saved = await runner.session_service.get_session(app_name="trace_test", user_id="manager", session_id=session.id)
        snapshots = [value for key, value in saved.state.items() if key.startswith("ui:trace:") and value]
        assert {value["root_invocation_id"] for value in snapshots} == {second[0]["root_invocation_id"]}
    finally:
        await runner.close()


def test_trace_summaries_redact_credentials_and_do_not_expose_thought_fields():
    value = bounded({"password": "secret-value", "authorization": "Bearer abc", "thoughts": "hidden deliberation",
                     "email": "person@example.com", "safe_count": 3, "total_token_count": 40})
    assert value["password"] == value["authorization"] == value["thoughts"] == "[redacted]"
    assert value["email"] == "[email]" and value["safe_count"] == 3 and value["total_token_count"] == 40


class ConfirmationModel(BaseLlm):
    model: str = "confirmation-test-model"

    async def generate_content_async(self, llm_request, stream=False):
        responses = [part.function_response for content in llm_request.contents for part in content.parts or []
                     if part.function_response and part.function_response.name == "reviewed_action"]
        parts = [types.Part(text="Review complete.")] if responses else [types.Part(function_call=types.FunctionCall(
            name="reviewed_action", args={}, id=str(uuid.uuid4())))]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


def reviewed_action(tool_context: ToolContext) -> dict:
    if tool_context.tool_confirmation is None:
        tool_context.request_confirmation(hint="Review this action", payload={"action": "test"})
        return {"status": "PENDING_CONFIRMATION"}
    return {"status": "SUCCESS" if tool_context.tool_confirmation.confirmed else "CANCELLED"}


@pytest.mark.asyncio
async def test_cancelled_confirmation_resume_keeps_trace_transport_valid():
    root = LlmAgent(name="review_agent", model=ConfirmationModel(), tools=[reviewed_action])
    app = App(name="confirmation_test", root_agent=root, plugins=[ExecutionTracePlugin()],
              resumability_config=ResumabilityConfig(is_resumable=True))
    runner = InMemoryRunner(app=app)
    try:
        session = await runner.session_service.create_session(app_name=app.name, user_id="manager", state=MANAGER)
        initial = await collect(runner, session, "Review an action")
        confirmation_event = next(event for event in initial if any(part.function_call and
            part.function_call.name == "adk_request_confirmation" for part in (event.content.parts if event.content else []) or []))
        call = next(part.function_call for part in confirmation_event.content.parts
                    if part.function_call and part.function_call.name == "adk_request_confirmation")
        resumed = [event async for event in runner.run_async(user_id=session.user_id, session_id=session.id,
            invocation_id=confirmation_event.invocation_id,
            new_message=types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
                id=call.id, name="adk_request_confirmation", response={"confirmed": False}))]))]
        rows = spans(resumed)
        action = next(row for row in rows if row["kind"] == "tool" and row["name"] == "reviewed_action")
        assert action["output"]["status"] == "CANCELLED"
        assert action["duration_ms"] >= 0
        assert len({row["root_invocation_id"] for row in rows}) == 1
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_manual_reads_measure_individual_duration_not_batch_latency(fake_backend, monkeypatch):
    read = fake_backend.get_osa_exceptions

    def slow_read(**kwargs):
        time.sleep(0.15)
        return read(**kwargs)

    monkeypatch.setattr(fake_backend, "get_osa_exceptions", slow_read)
    agent = BriefingSignals(name="briefing_inventory", area="inventory", output_key="temp:briefing_inventory")
    runner = InMemoryRunner(agent=agent, app_name="timing_test", plugins=[ExecutionTracePlugin()])
    try:
        session = await runner.session_service.create_session(app_name="timing_test", user_id="manager", state=MANAGER)
        rows = spans(await collect(runner, session, "Opening priorities"))
        slow = next(row for row in rows if row["name"] == "get_osa_exceptions")
        fast = next(row for row in rows if row["name"] == "get_merchandising_work")
        assert slow["duration_ms"] >= 150
        assert fast["duration_ms"] < slow["duration_ms"] / 2
    finally:
        await runner.close()


class TransferModel(BaseLlm):
    model: str = "transfer-test-model"
    calls: int = 0

    async def generate_content_async(self, llm_request, stream=False):
        self.calls += 1
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(
            function_call=types.FunctionCall(name="transfer_to_agent",
                args={"agent_name": "associate_development"}, id=str(uuid.uuid4())))]))


class DevelopmentModel(BaseLlm):
    model: str = "development-test-model"
    requests: list[str] = []

    async def generate_content_async(self, llm_request, stream=False):
        latest = next(content for content in reversed(llm_request.contents)
                      if content.role == "user" and any(part.text for part in content.parts or []))
        question = "".join(part.text or "" for part in latest.parts)
        self.requests.append(question)
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=
            "The same pick can have both signals; seven plus four is not eleven distinct picks."
            if "eleven" in question else "Stock-location practice is available.")]))


@pytest.mark.asyncio
@pytest.mark.parametrize("resumable", [False, True])
@pytest.mark.parametrize("tracing", [False, True])
async def test_trace_completion_preserves_development_as_active_agent_across_turns(resumable, tracing):
    """Observability must not make a completed parent the next conversational speaker."""
    root_model, development_model = TransferModel(), DevelopmentModel()
    development = LlmAgent(name="associate_development", model=development_model,
                           disallow_transfer_to_peers=True)
    root = LlmAgent(name="store_manager_agent", model=root_model, sub_agents=[development])
    app = App(name="transfer_trace", root_agent=root,
              plugins=[ExecutionTracePlugin()] if tracing else [],
              resumability_config=ResumabilityConfig(is_resumable=resumable))
    runner = InMemoryRunner(app=app)
    try:
        session = await runner.session_service.create_session(app_name=app.name, user_id="manager", state=MANAGER)
        first = await collect(runner, session, "What short learning activity helps stock locations?")
        second = await collect(runner, session, "Do seven flags plus four interruptions mean eleven delayed picks?")
        assert root_model.calls == 1
        assert len(development_model.requests) == 2
        assert "eleven" in development_model.requests[-1]
        assert not any(part.function_call for event in second
                       for part in (event.content.parts if event.content else []) or [])
        if tracing:
            for events in (first, second):
                completions = [event for event in events if not event.content
                               and any(key.startswith("ui:trace:") for key in event.actions.state_delta)
                               and any(span["kind"] == "agent" and span["status"] == "ok"
                                       for snapshot in event.actions.state_delta.values() if isinstance(snapshot, dict)
                                       for span in snapshot.get("spans", []) if span["agent"] == event.author)]
                assert completions and all(event.actions.end_of_agent for event in completions)
            assert all(span["duration_ms"] is not None for span in spans(first))
            assert {span["id"] for span in spans(first)}.isdisjoint(span["id"] for span in spans(second))
            saved = await runner.session_service.get_session(app_name=app.name, user_id="manager", session_id=session.id)
            snapshots = [snapshot for key, snapshot in saved.state.items() if key.startswith("ui:trace:") and snapshot]
            assert {snapshot["invocation_id"] for snapshot in snapshots} == {second[0].invocation_id}
    finally:
        await runner.close()


def test_task_agent_has_only_finish_task_return_and_development_cannot_transfer_to_peers():
    from google.adk.flows.llm_flows.agent_transfer import _get_transfer_targets

    from agents.cymbal_store_ops.sub_agents.associate_development import make_associate_development
    from agents.cymbal_store_ops.sub_agents.store_tasks import make_store_tasks

    task, development = make_store_tasks(), make_associate_development()
    root = LlmAgent(name="store_manager_agent", sub_agents=[task, development])
    assert _get_transfer_targets(task) == []
    assert _get_transfer_targets(development) == [root]


class HandoffModel(BaseLlm):
    model: str = "handoff-test-model"
    actor: str

    async def generate_content_async(self, llm_request, stream=False):
        latest = next(content for content in reversed(llm_request.contents)
                      if content.role == "user" and any(part.text for part in content.parts or []))
        returning = any("opening priorities" in (part.text or "") for part in latest.parts)
        destination = ("store_manager_agent" if returning else "associate_development")
        transfer = (self.actor == "associate_development") == returning
        part = types.Part(function_call=types.FunctionCall(name="transfer_to_agent",
            args={"agent_name": destination}, id=str(uuid.uuid4()))) if transfer else types.Part(text="Here is the answer.")
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


@pytest.mark.asyncio
async def test_development_handoff_to_root_preserves_current_turn_trace():
    development = LlmAgent(name="associate_development", model=HandoffModel(actor="associate_development"),
                           disallow_transfer_to_peers=True)
    root = LlmAgent(name="store_manager_agent", model=HandoffModel(actor="store_manager_agent"), sub_agents=[development])
    app = App(name="return_trace", root_agent=root, plugins=[ExecutionTracePlugin()],
              resumability_config=ResumabilityConfig(is_resumable=True))
    runner = InMemoryRunner(app=app)
    try:
        session = await runner.session_service.create_session(app_name=app.name, user_id="manager", state=MANAGER)
        first = spans(await collect(runner, session, "What learning is available?"))
        second = spans(await collect(runner, session, "Show opening priorities instead."))
        assert {span["name"] for span in second if span["kind"] == "agent"} == {
            "associate_development", "store_manager_agent"}
        assert {span["id"] for span in first}.isdisjoint(span["id"] for span in second)
        assert all(span["duration_ms"] is not None for span in second)
        assert len({span["root_invocation_id"] for span in second}) == 1
    finally:
        await runner.close()


def test_finished_span_keeps_first_result_when_later_callback_short_circuits():
    from types import SimpleNamespace

    from agents.cymbal_store_ops.trace import finish_span, start_span

    context = SimpleNamespace(agent=SimpleNamespace(name="root"), session=SimpleNamespace(state={}), invocation_id="test")
    sid = start_span(context, kind="model", name="observed-model")
    finish_span(context, sid, output={"usage": {"total_token_count": 30}})
    before = context.session.state["ui:trace:root"]["spans"][0].copy()
    finish_span(context, sid, output={"terminal": True})
    assert context.session.state["ui:trace:root"]["spans"][0] == before
