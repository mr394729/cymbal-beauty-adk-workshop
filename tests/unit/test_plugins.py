import asyncio

from google.genai import types

from agents.cymbal_store_ops.plugins import STOPPED, IngressRedactionPlugin, LoopGuardPlugin


class _Ctx:
    def __init__(self, invocation_id="inv-1", agent_name="store_manager_agent"):
        self.invocation_id, self.agent_name = invocation_id, agent_name
        self.state = {}


class _Tool:
    def __init__(self, name):
        self.name = name


def test_ingress_plugin_redacts_the_user_message():
    plugin = IngressRedactionPlugin()
    message = types.Content(role="user", parts=[types.Part(text="call me on (312) 555-0100")])
    out = asyncio.run(plugin.on_user_message_callback(invocation_context=None, user_message=message))
    assert out is message and "[phone redacted]" in message.parts[0].text
    clean = types.Content(role="user", parts=[types.Part(text="what is on the shelf?")])
    assert asyncio.run(plugin.on_user_message_callback(invocation_context=None, user_message=clean)) is None


def test_loop_guard_stops_a_request_after_the_model_call_cap():
    guard = LoopGuardPlugin(max_model_calls=3)
    ctx = _Ctx()
    for _ in range(3):
        assert asyncio.run(guard.before_model_callback(callback_context=ctx, llm_request=None)) is None
    stopped = asyncio.run(guard.before_model_callback(callback_context=ctx, llm_request=None))
    assert stopped.content.parts[0].text == STOPPED.format(n=3)
    # a new request starts from zero
    assert asyncio.run(guard.before_model_callback(callback_context=_Ctx("inv-2"), llm_request=None)) is None


def test_loop_guard_refuses_the_same_tool_call_after_the_repeat_cap():
    guard = LoopGuardPlugin(max_repeats=2)
    ctx = _Ctx()
    args = {"product_name": "Lumière Hydra Cream"}
    for _ in range(2):
        assert asyncio.run(guard.before_tool_callback(tool=_Tool("check_store_stock"), tool_args=args, tool_context=ctx)) is None
    refused = asyncio.run(guard.before_tool_callback(tool=_Tool("check_store_stock"), tool_args=args, tool_context=ctx))
    assert refused["status"] == "ERROR" and refused["code"] == "repeated_call" and "Do not call it again" in refused["error_details"]
    # different arguments, or the same call in the next request, are fine
    assert asyncio.run(guard.before_tool_callback(tool=_Tool("check_store_stock"), tool_args={"product_name": "Bloom Concealer"}, tool_context=ctx)) is None
    assert asyncio.run(guard.before_tool_callback(tool=_Tool("check_store_stock"), tool_args=args, tool_context=_Ctx("inv-2"))) is None
