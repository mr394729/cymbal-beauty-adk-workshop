"""App-level plugins: ingress PII redaction (before the message is stored) and a loop guard on every request."""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins import BasePlugin
from google.adk.tools import BaseTool, ToolContext
from google.genai import types

from agents.cymbal_store_ops.callbacks import redact

logger = logging.getLogger(__name__)


class IngressRedactionPlugin(BasePlugin):
    """Redacts emails/phones in the user message before it is appended to the session or seen by any agent."""

    def __init__(self) -> None:
        super().__init__(name="ingress_redaction")

    async def on_user_message_callback(self, *, invocation_context: InvocationContext,
                                       user_message: types.Content) -> types.Content | None:
        changed = False
        for part in user_message.parts or []:
            if part.text:
                new = redact(part.text)
                if new != part.text:
                    part.text, changed = new, True
        return user_message if changed else None


STOPPED = "I couldn’t complete that check. Please try a more specific request."


def _terminal_response(context, *, cancelled=False):
    """End model work in code, preserving task hand-back and public reply contracts."""
    answer = "Cancelled. That action was not carried out." if cancelled else STOPPED
    if context.agent_name == "store_tasks":
        return LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(
            name="finish_task", args={"result": answer}))]))
    context.state["ui:next_actions"] = []
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=answer)]))


class LoopGuardPlugin(BasePlugin):
    """Bounds one request in code: at most `max_model_calls` model calls per invocation, and at most `max_repeats`
    calls of the same tool with the same arguments.

    Why: a mid-shift follow-up ("when is the replenishment landing?") once ran 3,005 s and 500 model calls with no
    answer, ending in ADK's own ceiling (`RunConfig.max_llm_calls`), which the caller sees as an exception, not a
    reply. The repeat rule records the first over-limit call and ends the next model step in code. A declined
    write also ends model work for that invocation, including a task-mode hand-back before the root replies.
    Counters live in the plugin, keyed by invocation id; terminal markers carry that id in session state, so
    subsequent explicit user requests remain independent."""

    def __init__(self, max_model_calls: int = 30, max_repeats: int = 3) -> None:
        super().__init__(name="loop_guard")
        self.max_model_calls, self.max_repeats = max_model_calls, max_repeats
        self._counts: dict[str, int] = {}

    def _bump(self, key: str) -> int:
        n = self._counts.get(key, 0) + 1
        self._counts[key] = n
        while len(self._counts) > 4096:                       # bounded: the oldest invocations fall off
            del self._counts[next(iter(self._counts))]
        return n

    async def before_model_callback(self, *, callback_context: CallbackContext,
                                    llm_request: LlmRequest) -> LlmResponse | None:
        declined = callback_context.state.get("last_declined_action") or {}
        if declined.get("invocation_id") == callback_context.invocation_id:
            return _terminal_response(callback_context, cancelled=True)
        stopped = callback_context.state.get("request_stop") or {}
        if stopped.get("invocation_id") == callback_context.invocation_id:
            return _terminal_response(callback_context)
        n = self._bump(f"model:{callback_context.invocation_id}")
        if n <= self.max_model_calls:
            return None
        logger.warning("loop_guard: %s stopped after %d model calls in invocation %s",
                       callback_context.agent_name, self.max_model_calls, callback_context.invocation_id)
        callback_context.state["request_stop"] = {"invocation_id": callback_context.invocation_id, "reason": "model_limit"}
        return _terminal_response(callback_context)

    async def before_tool_callback(self, *, tool: BaseTool, tool_args: dict[str, Any],
                                   tool_context: ToolContext) -> dict[str, Any] | None:
        digest = hashlib.sha256(json.dumps(tool_args, sort_keys=True, default=str).encode()).hexdigest()[:16]
        n = self._bump(f"tool:{tool_context.invocation_id}:{tool.name}:{digest}")
        if n <= self.max_repeats:
            return None
        logger.warning("loop_guard: %s called %d times with the same arguments in invocation %s",
                       tool.name, n, tool_context.invocation_id)
        tool_context.state["request_stop"] = {"invocation_id": tool_context.invocation_id,
                                             "reason": "repeated_tool", "tool": tool.name}
        return {"status": "ERROR", "code": "repeated_call",
                "error_details": f"{tool.name} was already called {self.max_repeats} times with these arguments in this "
                                 "request; use the result you have or say what is missing. Do not call it again."}
