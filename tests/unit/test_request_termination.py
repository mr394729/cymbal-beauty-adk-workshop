"""Real runner regressions for cancelled task delegation and repeated-read loops."""
import uuid

import pytest
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.apps.app import ResumabilityConfig
from google.adk.models import LlmResponse
from google.adk.models.base_llm import BaseLlm
from google.adk.runners import InMemoryRunner
from google.genai import types

from agents.cymbal_store_ops.chat_reply import ChatReply, ChatReplyPlugin
from agents.cymbal_store_ops.plugins import STOPPED, LoopGuardPlugin
from agents.cymbal_store_ops.sub_agents.store_tasks import make_store_tasks
from agents.cymbal_store_ops.tools.domain_tools import workshop_clock
from agents.cymbal_store_ops.trace import ExecutionTracePlugin


class RepeatingModel(BaseLlm):
    """Intentionally repeats a tool even after its error, to test a code-enforced stop."""
    model: str = "repeating-test"
    target: str = "workshop_clock"
    calls: int = 0

    async def generate_content_async(self, llm_request, stream=False):
        self.calls += 1
        args = {"request": "Create an investigation task for the Noir Velvet latch."} if self.target == "store_tasks" else {}
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(
            name=self.target, args=args, id=str(uuid.uuid4())))]))


class TaskModel(BaseLlm):
    model: str = "task-test"
    calls: int = 0

    async def generate_content_async(self, llm_request, stream=False):
        self.calls += 1
        have_status = any(part.function_response and part.function_response.name == "get_task_status"
                          for content in llm_request.contents for part in content.parts or [])
        name = "create_store_task" if have_status else "get_task_status"
        args = {"task_type": "investigation", "note": "Inspect the locked-case latch", "product_id": "P-0420"} if have_status else {"product_id": "P-0420"}
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(
            name=name, args=args, id=str(uuid.uuid4())))]))


def calls(events, name):
    return [part.function_call for event in events for part in (event.content.parts if event.content else []) or []
            if part.function_call and part.function_call.name == name]


async def send(runner, session, message, invocation_id=None):
    if isinstance(message, str):
        message = types.Content(role="user", parts=[types.Part(text=message)])
    return [event async for event in runner.run_async(user_id=session.user_id, session_id=session.id,
        invocation_id=invocation_id, new_message=message)]


@pytest.mark.asyncio
async def test_repeated_tool_guard_ends_request_without_another_model_call():
    model = RepeatingModel()
    root = LlmAgent(name="store_manager_agent", model=model, tools=[workshop_clock], output_schema=ChatReply)
    app = App(name="termination", root_agent=root, plugins=[LoopGuardPlugin(max_repeats=2), ChatReplyPlugin()])
    runner = InMemoryRunner(app=app)
    try:
        session = await runner.session_service.create_session(app_name=app.name, user_id="manager")
        events = await send(runner, session, "Check the clock")
        assert model.calls == 3 and len(calls(events, "workshop_clock")) == 3
        text = [part.text for event in events for part in (event.content.parts if event.content else []) or [] if part.text]
        assert text[-1] == STOPPED
        assert any(event.actions.state_delta.get("ui:next_actions") == [] for event in events)
        await send(runner, session, "Make a new check")
        assert model.calls == 6  # New request has a new invocation and is not permanently blocked.
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_declined_task_hands_back_once_without_retrying_or_reconfirming(fake_backend):
    root_model = RepeatingModel(target="store_tasks")
    task_model = TaskModel()
    task_agent = make_store_tasks()
    task_agent.model = task_model
    root = LlmAgent(name="store_manager_agent", model=root_model, sub_agents=[task_agent], output_schema=ChatReply)
    app = App(name="termination", root_agent=root, plugins=[LoopGuardPlugin(), ExecutionTracePlugin(), ChatReplyPlugin()],
              resumability_config=ResumabilityConfig(is_resumable=True))
    runner = InMemoryRunner(app=app)
    try:
        state = {"user:user_id": "U-M014", "user:store_id": "S-014", "user:role": "store_manager"}
        session = await runner.session_service.create_session(app_name=app.name, user_id="manager", state=state)
        initial_count = len(fake_backend.tasks)
        first = await send(runner, session, "Create a task to inspect the latch")
        confirmation = calls(first, "adk_request_confirmation")
        assert len(confirmation) == 1
        event = next(event for event in first if any(part.function_call and part.function_call.id == confirmation[0].id
                     for part in (event.content.parts if event.content else []) or []))
        response = types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            name="adk_request_confirmation", id=confirmation[0].id, response={"confirmed": False}))])
        resumed = await send(runner, session, response, event.invocation_id)
        assert len(fake_backend.tasks) == initial_count
        assert not calls(resumed, "adk_request_confirmation")
        assert not calls(resumed, "store_tasks")
        assert len(calls(resumed, "finish_task")) == 1
        assert root_model.calls == 1 and task_model.calls == 2
        text = [part.text for event in resumed for part in (event.content.parts if event.content else []) or [] if part.text]
        assert text[-1] == "Cancelled. That action was not carried out."
        assert any(event.actions.state_delta.get("ui:next_actions") == [] for event in resumed)
        later = await send(runner, session, "Create a new latch task")
        assert len(calls(later, "adk_request_confirmation")) == 1
    finally:
        await runner.close()
