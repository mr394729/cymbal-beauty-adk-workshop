"""Only the trusted initial event analysis is barred from initiating writes."""
import hashlib
from types import SimpleNamespace

import pytest
from google.genai import types

from agents.cymbal_store_ops.callbacks import enforce_role_before_tool


@pytest.mark.parametrize("name", ["create_store_task", "delegate_task", "complete_my_task", "report_my_task_blocker", "remember_work_preference"])
def test_event_cannot_write_but_later_human_turn_uses_normal_controls(name):
    message = "Analyze the recorded event and recommend a response."
    context = SimpleNamespace(state={"user:role": "store_manager", "_event_initial_message_sha256": hashlib.sha256(message.encode()).hexdigest()},
                              user_content=types.Content(parts=[types.Part(text=message)]))
    tool = SimpleNamespace(name=name)
    assert enforce_role_before_tool(tool, {}, context)["code"] == "event_read_only"
    context.user_content = types.Content(parts=[types.Part(text="Create that task for Jordan.")])
    assert enforce_role_before_tool(tool, {}, context) is None
    context.state["user:role"] = "associate"
    if name in {"create_store_task", "delegate_task"}:
        assert enforce_role_before_tool(tool, {}, context)["status"] == "ERROR"
