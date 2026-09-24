"""The guardrails are wired and behave deterministically; no model."""
from __future__ import annotations

from google.genai import types

from agents.cymbal_store_ops.plugins import IngressRedactionPlugin

MANAGER = {"user:user_id": "U-M014", "user:store_id": "S-014", "user:role": "store_manager"}


class Ctx:
    def __init__(self, state: dict) -> None:
        self.state = state


class Tool:
    def __init__(self, name: str) -> None:
        self.name = name


def test_callbacks_and_plugin_wired(quickstart):
    agent = quickstart.root_agent
    assert agent.before_model_callback is quickstart.redact_before_model and agent.before_tool_callback is quickstart.guard_tools
    assert any(isinstance(p, IngressRedactionPlugin) for p in quickstart.app.plugins)
    assert [getattr(t, "__name__", "") for t in agent.tools] == ["identify_demo_user", "get_coaching_signals", "get_shrink_signals"]


def test_names_and_phones_never_reach_the_model(quickstart, fake_backend):
    from google.adk.models.llm_request import LlmRequest

    request = LlmRequest(contents=[
        types.Content(role="user", parts=[types.Part(text="Priya's cell is 312-555-0142, mail priya@example.com. Is Noor ok?")]),
        types.Content(role="model", parts=[types.Part(text="Priya is on shift.")])])
    quickstart.redact_before_model(Ctx(dict(MANAGER)), request)
    user, model = request.contents[0].parts[0].text, request.contents[1].parts[0].text
    assert user == "A-1004's cell is [phone redacted], mail [email redacted]. Is A-1007 ok?"
    assert model == "Priya is on shift."      # only user turns are rewritten


def test_pseudonymize_matches_whole_capitalised_names_only(quickstart):
    roster = {"Priya": "A-1004", "Maya": "A-1002"}
    assert quickstart.pseudonymize("Priya and Mayah met priya", roster) == "A-1004 and Mayah met priya"


def test_role_gate_and_store_scope(quickstart):
    associate = Ctx({**MANAGER, "user:role": "associate", "user:user_id": "A-1004"})
    assert quickstart.guard_tools(Tool("get_coaching_signals"), {"associate_id": "A-1007"}, associate)["status"] == "ERROR"
    assert quickstart.guard_tools(Tool("get_coaching_signals"), {"associate_id": "A-1007"}, Ctx(dict(MANAGER))) is None
    other_store = quickstart.guard_tools(Tool("get_shrink_signals"), {"store_id": "S-002"}, Ctx(dict(MANAGER)))
    assert other_store["status"] == "ERROR" and "S-014" in other_store["error_details"]


def test_hr_refusal_sentence_is_in_the_instruction(quickstart):
    assert quickstart.HR_REFUSAL in quickstart.root_agent.instruction
