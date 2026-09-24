"""Real ADK nesting proves that event write boundaries survive replaced child user content."""

from __future__ import annotations

import asyncio
import hashlib
import uuid

import pytest
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.apps.app import ResumabilityConfig
from google.adk.models import LlmResponse
from google.adk.models.base_llm import BaseLlm
from google.adk.runners import InMemoryRunner
from google.adk.tools import ToolContext
from google.adk.tools.agent_tool import AgentTool
from google.genai import types
from pydantic import BaseModel, Field

from agents.cymbal_store_ops.callbacks import (
    enforce_role_before_tool,
    set_event_read_only_before_model,
)


class Query(BaseModel):
    request: str


class ScriptedModel(BaseLlm):
    model: str = "offline-event-boundary"
    root: bool = False
    task: bool = False
    seen_write_responses: list[dict] = Field(default_factory=list)

    async def generate_content_async(self, llm_request, stream=False):
        self.seen_write_responses.extend(
            p.function_response.response
            for c in llm_request.contents
            for p in c.parts or []
            if p.function_response and p.function_response.name == "create_store_task"
        )
        latest = max(
            (
                i
                for i, c in enumerate(llm_request.contents)
                if c.role == "user" and any(p.text for p in c.parts or [])
            ),
            default=-1,
        )
        answered = any(
            p.function_response for c in llm_request.contents[latest + 1 :] for p in c.parts or []
        )
        if answered:
            part = (
                types.Part(
                    function_call=types.FunctionCall(
                        name="finish_task", args={"result": "Handled"}, id=str(uuid.uuid4())
                    )
                )
                if self.task
                else types.Part(text="Handled")
            )
        else:
            part = types.Part(
                function_call=types.FunctionCall(
                    name="worker" if self.root else "create_store_task",
                    args={"request": "Create the task now"} if self.root else {},
                    id=str(uuid.uuid4()),
                )
            )
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["agent_tool", "task"])
async def test_nested_event_blocked_then_fresh_human_reaches_normal_confirmation(kind):
    entered = []

    def create_store_task(tool_context: ToolContext) -> dict:
        """Request confirmation for a task."""
        entered.append(
            {
                "read_only": tool_context.state.get("temp:event_read_only"),
                "message": tool_context.user_content.parts[0].text,
            }
        )
        tool_context.request_confirmation(hint="Create this task?", payload={"task": "review"})
        entered[-1]["confirmation_requested"] = bool(tool_context.actions.requested_tool_confirmations)
        return {"status": "PENDING_CONFIRMATION"}

    child = LlmAgent(
        name="worker",
        model=ScriptedModel(task=kind == "task"),
        tools=[create_store_task],
        before_tool_callback=enforce_role_before_tool,
        input_schema=Query,
        mode="task" if kind == "task" else None,
    )
    root = LlmAgent(
        name="store_manager_agent",
        model=ScriptedModel(root=True),
        tools=[AgentTool(child)] if kind == "agent_tool" else [],
        sub_agents=[child] if kind == "task" else [],
        before_model_callback=set_event_read_only_before_model,
        before_tool_callback=enforce_role_before_tool,
    )
    runner = InMemoryRunner(
        app=App(
            name="event_guard",
            root_agent=root,
            resumability_config=ResumabilityConfig(is_resumable=True),
        )
    )
    message = "Analyze the observed pickup deadline without making changes."
    session = await runner.session_service.create_session(
        app_name="event_guard",
        user_id="review-user",
        state={
            "user:role": "store_manager",
            "user:store_id": "S-014",
            "user:user_id": "U-M014",
            "_event_initial_message_sha256": hashlib.sha256(message.encode()).hexdigest(),
        },
    )
    try:
        first = [
            ev
            async for ev in runner.run_async(
                user_id=session.user_id,
                session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text=message)]),
            )
        ]
        assert first
        assert not entered
        assert any(r.get("code") == "event_read_only" for r in child.model.seen_write_responses)
        second = [
            ev
            async for ev in runner.run_async(
                user_id=session.user_id,
                session_id=session.id,
                new_message=types.Content(
                    role="user",
                    parts=[types.Part(text="Please create that task; show me the confirmation.")],
                ),
            )
        ]
        assert len(entered) == 1 and not entered[0]["read_only"]
        assert second and entered[0]["confirmation_requested"]
        # Plain AgentTool hides its child events. Task mode propagates confirmation to the UI.
        if kind == "task":
            assert any(ev.actions.requested_tool_confirmations for ev in second)

        # Two concurrent conversations share this agent tree, but not the task-local boundary.
        async def turn(text):
            other = await runner.session_service.create_session(
                app_name="event_guard",
                user_id="review-user",
                state={
                    "user:role": "store_manager",
                    "user:store_id": "S-014",
                    "user:user_id": "U-M014",
                    "_event_initial_message_sha256": hashlib.sha256(message.encode()).hexdigest(),
                },
            )
            return [
                ev
                async for ev in runner.run_async(
                    user_id=other.user_id,
                    session_id=other.id,
                    new_message=types.Content(role="user", parts=[types.Part(text=text)]),
                )
            ]

        await asyncio.gather(turn(message), turn("Please create a task and ask me to confirm."))
        assert len(entered) == 2
        assert all(not entry["read_only"] for entry in entered)
    finally:
        await runner.close()
