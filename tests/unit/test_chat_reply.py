"""Normal replies keep useful choices; pure refusals clear activities."""
import json

import pytest
from google.adk.events import Event, EventActions
from google.genai import types
from pydantic import ValidationError

from agents.cymbal_store_ops.chat_reply import ChatReply, ChatReplyPlugin


def actions(count):
    return [{"label": f"Activity {i}", "prompt": f"Review supported activity {i}."} for i in range(count)]


@pytest.mark.parametrize("count", [0, 3, 4, 5])
def test_refusal_or_normal_action_counts_are_accepted(count):
    reply = ChatReply(answer="A concise answer.", next_actions=actions(count))
    assert len(reply.next_actions) == count


@pytest.mark.parametrize("count", [1, 2, 6])
def test_incomplete_or_excessive_activity_sets_are_rejected(count):
    with pytest.raises(ValidationError):
        ChatReply(answer="A concise answer.", next_actions=actions(count))


@pytest.mark.asyncio
@pytest.mark.parametrize("author", ["store_manager_agent", "associate_development"])
async def test_pure_refusal_clears_prior_actions_and_keeps_readable_answer(author):
    payload = {"answer": "I can review those records, but cannot delete them.", "next_actions": []}
    event = Event(author=author, actions=EventActions(state_delta={"ui:next_actions": actions(3)}),
                  content=types.Content(role="model", parts=[types.Part(text=json.dumps(payload))]))
    shaped = await ChatReplyPlugin().on_event_callback(invocation_context=None, event=event)
    assert shaped.content.parts[0].text == payload["answer"]
    assert shaped.actions.state_delta["ui:next_actions"] == []


def test_schema_uses_plain_array_bounds_supported_by_model_api():
    schema = ChatReply.model_json_schema()["properties"]["next_actions"]
    assert schema["type"] == "array"
    assert schema["minItems"] == 0 and schema["maxItems"] == 5
    assert "anyOf" not in schema and "oneOf" not in schema
