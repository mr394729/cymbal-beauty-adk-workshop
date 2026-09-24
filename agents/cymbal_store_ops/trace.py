"""Bounded, session-scoped execution traces for the chat activity inspector.

These are observed ADK spans, not model reasoning. Snapshots use ordinary state deltas so an
AgentTool's nested runner transports its spans back to the calling conversation.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

from google.adk.plugins import BasePlugin

TRACE_PREFIX = "ui:trace:"
MAX_SPANS = 48
_PRIVATE = re.compile(r"password|secret|authorization|cookie|credential|api.?key|thought|thinking|private.?key|"
                      r"(?:access|refresh|id)[_-]?token|^token$", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_BEARER = re.compile(r"(?i)bearer\s+\S+|ya29\.[\w.-]+")


def bounded(value: Any, depth: int = 0) -> Any:
    """Bound tool summaries and redact sensitive fields before they enter persistent state."""
    if depth > 4:
        return "[details omitted]"
    if isinstance(value, dict):
        selected = list(value.items())[:16]
        return {str(key): "[redacted]" if _PRIVATE.search(str(key)) else bounded(item, depth + 1)
                for key, item in selected}
    if isinstance(value, (list, tuple)):
        return [bounded(item, depth + 1) for item in value[:8]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = _BEARER.sub("[redacted]", _EMAIL.sub("[email]", str(value)))
    return text[:600] + ("…" if len(text) > 600 else "")


def _summary(value, limit=2500):
    safe = bounded(value)
    encoded = json.dumps(safe, ensure_ascii=False, default=str)
    return safe if len(encoded) <= limit else {"preview": encoded[:limit], "truncated": True}


def _invocation(context):
    return context.get_invocation_context() if hasattr(context, "get_invocation_context") else context


def _agent(context):
    return _invocation(context).agent.name


def _spans(context):
    state = _invocation(context).session.state
    for key, snapshot in state.items():
        if key.startswith(TRACE_PREFIX) and isinstance(snapshot, dict):
            yield from snapshot.get("spans", [])


def _save(context, span):
    inv = _invocation(context)
    key = TRACE_PREFIX + span["agent"]
    old = inv.session.state.get(key) or {}
    spans = list(old.get("spans", [])) if old.get("invocation_id") == span["invocation_id"] else []
    spans = [item for item in spans if item["id"] != span["id"]]
    spans.append(span)
    snapshot = {"invocation_id": span["invocation_id"], "root_invocation_id": span["root_invocation_id"],
                "spans": spans[-MAX_SPANS:]}
    # The session belongs to this invocation; no plugin-global mutable collection is used.
    inv.session.state[key] = snapshot
    if hasattr(context, "state"):
        context.state[key] = snapshot
    return snapshot


def start_span(context, *, kind: str, name: str, inputs=None, span_id=None, parent_id=None):
    inv = _invocation(context)
    agent = _agent(context)
    if parent_id is None and kind != "agent":
        parents = [span for span in _spans(context) if span["kind"] == "agent" and span["agent"] == agent
                   and span["invocation_id"] == inv.invocation_id and span["status"] == "running"]
        parent_id = parents[-1]["id"] if parents else None
    parent = next((span for span in _spans(context) if span["id"] == parent_id), None)
    span = {"id": span_id or str(uuid.uuid4()), "parent_id": parent_id,
            "invocation_id": inv.invocation_id, "agent": agent, "name": name, "kind": kind,
            "root_invocation_id": parent.get("root_invocation_id", parent["invocation_id"]) if parent else inv.invocation_id,
            "start_ms": round(time.time() * 1000, 3), "duration_ms": None, "status": "running",
            "input": _summary(inputs, 1200), "output": None}
    inv.session.state["temp:trace:clock:" + span["id"]] = time.perf_counter()
    _save(context, span)
    return span["id"]


def finish_span(context, span_id, *, output=None, status="ok"):
    inv = _invocation(context)
    span = next((item for item in _spans(context) if item["id"] == span_id), None)
    if span is None or span["status"] != "running":
        return
    start = inv.session.state.pop("temp:trace:clock:" + span_id, None)
    duration = round((time.perf_counter() - start) * 1000, 3) if start is not None else span["duration_ms"]
    _save(context, {**span, "duration_ms": duration, "status": status, "output": _summary(output)})


def record_model_input(context, llm_request):
    """Record the final request size after an agent callback has projected its history."""
    inv = _invocation(context)
    sid = inv.session.state.get(f"temp:trace:model:{inv.invocation_id}:{_agent(context)}")
    span = next((item for item in _spans(context) if item["id"] == sid), None)
    if span is not None:
        _save(context, {**span, "input": {"message_count": len(llm_request.contents or []),
                                         "measurement": "after_agent_callback"}})


def result_status(result):
    if isinstance(result, dict):
        if result.get("code") in {"forbidden", "sign_in_required"}:
            return "blocked"
        if result.get("status") == "ERROR":
            return "error"
    return "ok"


def _visible(content):
    return "".join(part.text or "" for part in (content.parts if content else []) or [] if not part.thought)


class ExecutionTracePlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="execution_trace")

    async def before_agent_callback(self, *, agent, callback_context):
        inv = _invocation(callback_context)
        running = [span for span in _spans(callback_context) if span["status"] == "running"]
        # A nested AgentTool runner inherits the outer tool's snapshot. Its root has no parent_agent.
        candidates = [span for span in running if span["kind"] == "tool" and span["name"] == agent.name]
        if not candidates and not any(span["invocation_id"] == inv.invocation_id
                                      for span in _spans(callback_context)):
            # A fresh outer turn does not seed every historical trace into a future AgentTool call.
            # ADK may start this turn directly in the last transferred-to chat agent.
            for key in list(inv.session.state):
                if key.startswith(TRACE_PREFIX):
                    callback_context.state[key] = None
        if not candidates and agent.parent_agent:
            candidates = [span for span in _spans(callback_context) if span["kind"] == "agent"
                          and span["name"] == agent.parent_agent.name
                          and span["invocation_id"] == inv.invocation_id]
        parent = candidates[-1]["id"] if candidates else None
        sid = start_span(callback_context, kind="agent", name=agent.name, parent_id=parent,
                         inputs={"request": _visible(inv.user_content)})
        inv.session.state[f"temp:trace:agent:{inv.invocation_id}:{agent.name}"] = sid

    async def after_agent_callback(self, *, agent, callback_context):
        inv = _invocation(callback_context)
        sid = inv.session.state.get(f"temp:trace:agent:{inv.invocation_id}:{agent.name}")
        if sid:
            visible = next((_visible(event.content) for event in reversed(inv.session.events)
                            if event.invocation_id == inv.invocation_id and event.author == agent.name
                            and event.content and event.content.role == "model" and _visible(event.content)), "")
            finish_span(callback_context, sid, output={"text": visible} if visible else {"completed": True})
            # This callback runs after the agent has completed. Its trace-only state event
            # must be a lifecycle event, not a new conversational turn: ADK otherwise
            # treats its author as the active speaker on the next user message.
            callback_context.actions.end_of_agent = True

    async def before_model_callback(self, *, callback_context, llm_request):
        inv = _invocation(callback_context)
        sid = start_span(callback_context, kind="model", name=str(llm_request.model or "model"),
                         inputs={"message_count": len(llm_request.contents or [])})
        inv.session.state[f"temp:trace:model:{inv.invocation_id}:{_agent(callback_context)}"] = sid

    async def after_model_callback(self, *, callback_context, llm_response):
        if llm_response.partial:
            return
        inv = _invocation(callback_context)
        sid = inv.session.state.get(f"temp:trace:model:{inv.invocation_id}:{_agent(callback_context)}")
        content = llm_response.content
        calls = [part.function_call.name for part in (content.parts if content else []) or [] if part.function_call]
        if sid:
            usage = llm_response.usage_metadata
            counts = {key: getattr(usage, key, None) for key in
                      ("prompt_token_count", "candidates_token_count", "total_token_count")} if usage else {}
            if usage:
                # Aggregate usage only; private reasoning content is never included.
                counts["reasoning_token_count"] = getattr(usage, "thoughts_token_count", None)
                counts["cached_token_count"] = getattr(usage, "cached_content_token_count", None)
            finish_span(callback_context, sid, output={"visible_text_characters": len(_visible(content)),
                        "tool_calls": calls, "usage": counts},
                        status="error" if llm_response.error_code else "ok")

    async def before_tool_callback(self, *, tool, tool_args, tool_context):
        start_span(tool_context, kind="tool", name=tool.name, inputs=tool_args,
                   span_id=tool_context.function_call_id or str(uuid.uuid4()))

    async def after_tool_callback(self, *, tool, tool_args, tool_context, result):
        if tool_context.function_call_id:
            finish_span(tool_context, tool_context.function_call_id, output=result, status=result_status(result))

    async def on_tool_error_callback(self, *, tool, tool_args, tool_context, error):
        if tool_context.function_call_id:
            finish_span(tool_context, tool_context.function_call_id, output={"error_type": type(error).__name__}, status="error")

    async def on_model_error_callback(self, *, callback_context, llm_request, error):
        inv = _invocation(callback_context)
        sid = inv.session.state.get(f"temp:trace:model:{inv.invocation_id}:{_agent(callback_context)}")
        if sid:
            finish_span(callback_context, sid, output={"error_type": type(error).__name__}, status="error")

    async def on_agent_error_callback(self, *, agent, callback_context, error):
        inv = _invocation(callback_context)
        sid = inv.session.state.get(f"temp:trace:agent:{inv.invocation_id}:{agent.name}")
        if sid:
            finish_span(callback_context, sid, output={"error_type": type(error).__name__}, status="error")

    async def on_event_callback(self, *, invocation_context, event):
        if event.actions.transfer_to_agent:
            # Transfer ends the source LLM's invocation path without after_agent_callback.
            # Record that real handoff boundary, while preserving its span as the child's parent.
            running = [span for span in _spans(invocation_context) if span["kind"] == "agent"
                       and span["agent"] == event.author and span["status"] == "running"
                       and span["invocation_id"] == invocation_context.invocation_id]
            for span in running:
                finish_span(invocation_context, span["id"],
                            output={"transferred_to": event.actions.transfer_to_agent})
        # Snapshot just this author; nested AgentTool snapshots already present in state_delta remain intact.
        key = TRACE_PREFIX + event.author
        snapshot = invocation_context.session.state.get(key)
        if snapshot and snapshot.get("invocation_id") == invocation_context.invocation_id:
            event.actions.state_delta[key] = snapshot
        # Mutation with None return lets subsequent plugins continue shaping the same event.
        return None
