"""Structured next actions travel in state; conversation history keeps the readable answer."""
from __future__ import annotations

from google.adk.plugins import BasePlugin
from google.genai import types
from pydantic import BaseModel, Field, field_validator


class NextAction(BaseModel):
    label: str = Field(description="A short activity label, two to six words", max_length=60)
    prompt: str = Field(max_length=300, description=
        "A complete request for a supported activity, naming its subject. Retain known product SKU and task IDs "
        "in this request even when the label uses a friendly name; include relevant deadlines. "
        "Keep a stored task deadline distinct from a proposed earlier work or review time; do not relabel one as the other. "
        "Never invent a first-person observation, completed physical work or a blocker. To complete work or "
        "report a blocker, request the workflow for the actual assigned task ID and ask for the person's "
        "outcome or reason before proposing a write. Only reuse an outcome the person has already reported. "
        "Maintenance means an internal inspection/investigation task, not an external facilities ticket. "
        "Suggest only reads and writes supported by available capabilities, not hypothetical reports or APIs. "
        "Do not fetch unknown IDs or details just to populate suggestions.")


class ChatReply(BaseModel):
    answer: str = Field(description="The concise answer for the store team, with readable local times and no tool jargon")
    next_actions: list[NextAction] = Field(min_length=0, max_length=5,
        description="For supported store work, provide 3–5 useful activities grounded in the conversation and "
                    "signed-in role. For a pure out-of-scope or unsupported-action refusal, return an empty list; "
                    "do not read data or transfer agents to fill buttons. Do not repeat completed work. "
                    "A suggested write remains subject to confirmation.")

    @field_validator("next_actions")
    @classmethod
    def supported_action_count(cls, actions: list[NextAction]) -> list[NextAction]:
        if actions and len(actions) < 3:
            raise ValueError("Use no activities for a pure refusal, otherwise provide 3–5 activities.")
        return actions


class ChatReplyPlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="chat_reply")

    async def on_event_callback(self, *, invocation_context, event):
        if event.author not in {"store_manager_agent", "associate_development"} or event.partial or not event.content:
            return None
        parts = event.content.parts or []
        if event.author == "store_manager_agent" and event.actions.skip_summarization:
            responses = [part.function_response for part in parts if part.function_response]
            if len(responses) == 1 and responses[0].name in {
                "deliver_store_report", "daily_briefing", "create_end_of_day_dashboard"}:
                response = responses[0]
                result = response.response or {}
                final = result.get("final_reply") or {}
                if (result.get("status") == "SUCCESS" and result.get("reply_completed") is True
                        and final.get("invocation_id") == event.invocation_id
                        and final.get("call_id") == response.id):
                    reply = ChatReply.model_validate(final)
                    if not reply.next_actions:
                        raise ValueError("A delivered reply requires suggested activities.")
                    # Preserve the actual function response in history; only presentation text is appended.
                    event.content.parts = [part for part in parts if part.function_response]
                    event.content.parts.append(types.Part(text=reply.answer))
                    event.actions.state_delta["ui:next_actions"] = [action.model_dump() for action in reply.next_actions]
                    return event
        if any(p.function_call or p.function_response for p in parts):
            return None
        text = "".join(p.text or "" for p in parts if not p.thought).strip()
        if not text.startswith("{"):
            return None  # Framework error/loop-limit messages are ordinary text.
        reply = ChatReply.model_validate_json(text)
        event.content = types.Content(role="model", parts=[types.Part(text=reply.answer)])
        event.actions.state_delta["ui:next_actions"] = [a.model_dump() for a in reply.next_actions]
        return event
