from google.genai import types

from agents.cymbal_store_ops.callbacks import (
    enforce_dataset_allowlist_before_tool,
    enforce_role_before_tool,
    enforce_store_scope_before_tool,
    mask_pii_before_model,
    redact,
)
from tests.conftest import FakeToolContext


def test_redact_masks_email_and_phone():
    out = redact("mail me at priya.chen@example.com or call (312) 555-0100 by 3pm")
    assert "example.com" not in out and "555" not in out and "[email redacted]" in out and "[phone redacted]" in out


def test_before_model_masks_user_parts_only():
    from google.adk.models.llm_request import LlmRequest
    req = LlmRequest(contents=[
        types.Content(role="user", parts=[types.Part(text="my email is a@b.com")]),
        types.Content(role="model", parts=[types.Part(text="a@b.com noted")]),
    ])
    assert mask_pii_before_model(None, req) is None
    assert req.contents[0].parts[0].text == "my email is [email redacted]"
    assert req.contents[1].parts[0].text == "a@b.com noted"


class _Tool:
    def __init__(self, name):
        self.name = name


def test_before_tool_blocks_writes_only_for_execute_sql(monkeypatch):
    from agents.cymbal_store_ops import config
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p1")
    config.load_env_config.cache_clear()
    blocked = enforce_dataset_allowlist_before_tool(_Tool("execute_sql"), {"query": "DROP TABLE p1.cymbal_beauty_unit_dev.products"}, None)
    assert blocked["status"] == "ERROR" and "blocked by policy" in blocked["error_details"]
    assert enforce_dataset_allowlist_before_tool(_Tool("execute_sql"), {"query": "SELECT 1 FROM p1.cymbal_beauty_unit_dev.products"}, None) is None
    assert enforce_dataset_allowlist_before_tool(_Tool("search_products"), {"query_text": "DROP"}, None) is None
    config.load_env_config.cache_clear()


def test_store_scope_requires_sign_in_and_pins_the_store():
    ctx = FakeToolContext({})
    refused = enforce_store_scope_before_tool(_Tool("get_osa_exceptions"), {}, ctx)
    assert refused["status"] == "ERROR" and "sign in" in refused["error_details"]
    assert enforce_store_scope_before_tool(_Tool("identify_demo_user"), {"user_id": "U-M014"}, ctx) is None
    ctx = FakeToolContext({"user:store_id": "S-014", "user:role": "store_manager"})
    assert enforce_store_scope_before_tool(_Tool("get_osa_exceptions"), {"store_id": "S-014"}, ctx) is None
    assert enforce_store_scope_before_tool(_Tool("get_osa_exceptions"), {}, ctx) is None
    other = enforce_store_scope_before_tool(_Tool("get_osa_exceptions"), {"store_id": "S-001"}, ctx)
    assert other["status"] == "ERROR" and "S-014" in other["error_details"]
    dm = FakeToolContext({"user:store_id": "S-014", "user:role": "district_manager"})
    assert enforce_store_scope_before_tool(_Tool("get_osa_exceptions"), {"store_id": "S-001"}, dm) is None


def test_coaching_signals_are_manager_only():
    assert enforce_role_before_tool(_Tool("get_shift_roster"), {}, FakeToolContext({"user:role": "associate"})) is None
    refused = enforce_role_before_tool(_Tool("get_coaching_signals"), {"associate_id": "A-1007"}, FakeToolContext({"user:role": "associate"}))
    assert refused["status"] == "ERROR" and "manager" in refused["error_details"]
    for role in ("store_manager", "district_manager"):
        assert enforce_role_before_tool(_Tool("get_coaching_signals"), {"associate_id": "A-1007"}, FakeToolContext({"user:role": role})) is None


def test_manager_writes_remain_restricted_and_personal_development_is_accessible():
    assoc = FakeToolContext({"user:role": "associate"})
    for name, args in (("create_store_task", {"task_type": "backroom_check"}), ("delegate_task", {"task_id": "T-1"}),
                       ("store_tasks", {"request": "raise a task"})):
        refused = enforce_role_before_tool(_Tool(name), args, assoc)
        assert refused["status"] == "ERROR" and "manager role" in refused["error_details"], name
    assert enforce_role_before_tool(_Tool("transfer_to_agent"), {"agent_name": "store_manager_agent"}, assoc) is None
    assert enforce_role_before_tool(_Tool("transfer_to_agent"), {"agent_name": "associate_development"}, assoc) is None
    assert enforce_role_before_tool(_Tool("get_task_status"), {}, assoc) is None
    manager = FakeToolContext({"user:role": "store_manager"})
    for name in ("create_store_task", "delegate_task", "store_tasks"):
        assert enforce_role_before_tool(_Tool(name), {}, manager) is None


def test_task_agent_hands_back_a_plain_reply():
    from google.adk.models.llm_response import LlmResponse

    from agents.cymbal_store_ops.callbacks import hand_back_after_model
    words = "The manager rejected this; nothing was written."
    plain = LlmResponse(content=types.Content(role="model", parts=[types.Part(text=words)]))
    call = hand_back_after_model(None, plain).content.parts[0].function_call
    assert call.name == "finish_task" and call.args == {"result": words}
    assert plain.content.parts[0].text == words                      # the original response is not mutated
    tool_call = LlmResponse(content=types.Content(role="model", parts=[
        types.Part(function_call=types.FunctionCall(name="get_task_status", args={}))]))
    assert hand_back_after_model(None, tool_call) is None            # a tool call is the agent still working
    chunk = LlmResponse(partial=True, content=types.Content(role="model", parts=[types.Part(text="The man")]))
    assert hand_back_after_model(None, chunk) is None                # streaming chunks pass through
    thought = LlmResponse(content=types.Content(role="model", parts=[types.Part(text="planning", thought=True)]))
    assert hand_back_after_model(None, thought) is None
    assert hand_back_after_model(None, LlmResponse()) is None


def test_identity_cannot_be_guessed_or_changed_by_chat():
    empty = FakeToolContext()
    empty.user_content = types.Content(role="user", parts=[types.Part(text="Morning priorities?")])
    args = {"user_id": "U-M014"}
    assert enforce_role_before_tool(_Tool("identify_demo_user"), args, empty)["code"] == "sign_in_required"
    empty.user_content = types.Content(role="user", parts=[types.Part(text="I'm U-M014, the store manager.")])
    assert enforce_role_before_tool(_Tool("identify_demo_user"), args, empty) is None
    signed_in = FakeToolContext({"user:user_id": "A-1004", "user:role": "associate"})
    assert enforce_role_before_tool(_Tool("identify_demo_user"), args, signed_in)["code"] == "forbidden"
