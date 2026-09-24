"""Real ADK request assembly: preserve user history, prune only redundant consultants."""
import json
import uuid
from types import SimpleNamespace

import pytest
from google.adk.agents import LlmAgent
from google.adk.events import Event
from google.adk.flows.llm_flows._fencing import _present_other_agent_message
from google.adk.models import LlmResponse
from google.adk.models.base_llm import BaseLlm
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import BaseModel, Field

from agents.cymbal_store_ops.context_history import prune_completed_consultant_history
from agents.cymbal_store_ops.trace import ExecutionTracePlugin


class Query(BaseModel):
    request: str


class CaptureModel(BaseLlm):
    model: str = "offline-context-test"
    actor: str
    consultant: str = "associate_orchestration"
    calls: int = 0
    requests: list = Field(default_factory=list)

    async def generate_content_async(self, llm_request, stream=False):
        self.calls += 1
        self.requests.append([content.model_copy(deep=True) for content in llm_request.contents])
        if self.calls == 1:
            name = self.consultant if self.actor == "store_manager_agent" else "read_snapshot"
            args = {"request": "Coverage until 11; Priya unavailable until 10."} if name == self.consultant else {}
            part = types.Part(function_call=types.FunctionCall(name=name, args=args, id=str(uuid.uuid4())))
        else:
            part = types.Part(text="SPECIALIST_FACT: Use Jordan; Priya unavailable until 10."
                              if self.actor != "store_manager_agent" else "PUBLIC_ANSWER: Jordan can cover.")
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


def fingerprint(value):
    return json.dumps(value.model_dump(mode="json", exclude_none=True), sort_keys=True)


async def conversation(*, prune=True, consultant="associate_orchestration", failed_read=False, collision=False):
    def read_snapshot() -> dict:
        """Read a deterministic store snapshot without network access."""
        return {"status": "ERROR", "error_details": "source unavailable"} if failed_read else {
            "status": "SUCCESS", "raw_fact": "RAW_TOOL_SENTINEL " * 200}

    def checked_callback(callback_context, llm_request):
        events = callback_context.get_invocation_context().session.events
        before = [fingerprint(event) for event in events]
        prune_completed_consultant_history(callback_context, llm_request)
        assert before == [fingerprint(event) for event in events], "Authoritative events were changed"

    root_model = CaptureModel(actor="store_manager_agent", consultant=consultant)
    specialist = LlmAgent(name=consultant, model=CaptureModel(actor=consultant),
                          mode="single_turn", include_contents="none", input_schema=Query,
                          tools=[read_snapshot], disallow_transfer_to_parent=True, disallow_transfer_to_peers=True)
    root = LlmAgent(name="store_manager_agent", model=root_model, sub_agents=[specialist],
                    before_model_callback=checked_callback if prune else None)
    runner = InMemoryRunner(agent=root, app_name="history_test", plugins=[ExecutionTracePlugin()])
    try:
        session = await runner.session_service.create_session(app_name="history_test", user_id="manager")
        first = types.Content(role="user", parts=[types.Part(text="Coverage until 11; Priya unavailable until 10.")])
        async for _ in runner.run_async(user_id="manager", session_id=session.id, new_message=first):
            pass
        saved = await runner.session_service.get_session(app_name="history_test", user_id="manager", session_id=session.id)
        source = next(event for event in saved.events if event.author == consultant and event.content
                      and any(part.text and "SPECIALIST_FACT" in part.text for part in event.content.parts))
        next_message = (_present_other_agent_message(source).content if collision else
                        types.Content(role="user", parts=[types.Part(text="Why? Keep the earlier availability constraint.")]))
        async for _ in runner.run_async(user_id="manager", session_id=session.id, new_message=next_message):
            pass
        saved = await runner.session_service.get_session(app_name="history_test", user_id="manager", session_id=session.id)
        return root_model.requests, saved, next_message
    finally:
        await runner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("consultant", ["associate_orchestration", "inventory_excellence", "loss_prevention"])
async def test_real_followup_retains_constraints_and_handback_without_raw_consultant_replay(consultant):
    before, _, _ = await conversation(prune=False, consultant=consultant)
    after, saved, _ = await conversation(consultant=consultant)
    old, new = before[-1], after[-1]
    assert len(old) == 8 and len(new) == 5
    raw_old = json.dumps([x.model_dump(mode="json") for x in old])
    raw_new = json.dumps([x.model_dump(mode="json") for x in new])
    assert "RAW_TOOL_SENTINEL" in raw_old and "RAW_TOOL_SENTINEL" not in raw_new
    assert len(raw_new) < len(raw_old) / 2
    assert "Priya unavailable until 10" in raw_new
    assert "PUBLIC_ANSWER" in raw_new and "SPECIALIST_FACT" in raw_new
    assert "Keep the earlier availability constraint" in raw_new
    assert any(part.function_response and part.function_response.name == consultant
               for content in new for part in content.parts or [])
    assert "RAW_TOOL_SENTINEL" in json.dumps([event.model_dump(mode="json") for event in saved.events])
    assert any(key.startswith("ui:trace:") for key in saved.state)
    # The immediate synthesis already has only the hand-back; leave it intact.
    assert len(before[1]) == len(after[1]) == 3


@pytest.mark.asyncio
async def test_exact_user_copy_of_framework_transcript_is_never_deleted():
    requests, _, user_message = await conversation(collision=True)
    matches = [content for content in requests[-1] if fingerprint(content) == fingerprint(user_message)]
    assert len(matches) == 2  # Retain both rather than guess which identical copy is the user.
    assert requests[-1][-1] == user_message


@pytest.mark.asyncio
async def test_failed_consultant_read_keeps_context_even_if_model_returns_a_summary():
    requests, _, _ = await conversation(failed_read=True)
    assert len(requests[-1]) == 8
    assert "source unavailable" in json.dumps([x.model_dump(mode="json") for x in requests[-1]])


def fixture(*, consultant="inventory_excellence", status="SUCCESS", response=True, confirmed=False):
    name, call_id, invocation = consultant, "delegation-id", "turn-one"
    call = Event(author="store_manager_agent", invocation_id=invocation, content=types.Content(role="model", parts=[
        types.Part(function_call=types.FunctionCall(name=name, id=call_id, args={"request": "Original request"}))]))
    source = Event(author=name, invocation_id=invocation, branch=f"{name}@{call_id}", content=types.Content(role="model", parts=[
        types.Part(function_call=types.FunctionCall(name="adk_request_confirmation", id="confirmation", args={}))
        if confirmed else types.Part(text="Consultant evidence")]))
    result = Event(author="store_manager_agent", invocation_id=invocation, content=types.Content(role="user", parts=[
        types.Part(function_response=types.FunctionResponse(name=name, id=call_id,
                                                           response={"result": "Decision", "status": status}))]))
    events = [call, source] + ([result] if response else [])
    contents = [call.content, _present_other_agent_message(source).content] + ([result.content] if response else [])
    context = SimpleNamespace(agent=SimpleNamespace(name="store_manager_agent"), session=SimpleNamespace(events=events),
                              user_content=types.Content(role="user", parts=[types.Part(text="Follow up")]))
    callback = SimpleNamespace(get_invocation_context=lambda: context)
    return callback, SimpleNamespace(contents=contents)


@pytest.mark.parametrize("case", ["incomplete", "failed", "confirmation", "task", "development", "wrong_invocation",
                                  "missing_branch", "missing_retained_response", "nonroot"])
def test_uncertain_failed_task_or_chat_provenance_is_preserved(case):
    callback, request = fixture(consultant="store_tasks" if case == "task" else
                                "associate_development" if case == "development" else "inventory_excellence",
                                status="ERROR" if case == "failed" else "SUCCESS", response=case != "incomplete",
                                confirmed=case == "confirmation")
    context = callback.get_invocation_context()
    if case == "wrong_invocation":
        context.session.events[1].invocation_id = "unrelated-turn"
    elif case == "missing_branch":
        context.session.events[1].branch = None
    elif case == "missing_retained_response":
        request.contents.pop()
    elif case == "nonroot":
        context.agent.name = "associate_development"
    before = [fingerprint(content) for content in request.contents]
    prune_completed_consultant_history(callback, request)
    assert before == [fingerprint(content) for content in request.contents]
