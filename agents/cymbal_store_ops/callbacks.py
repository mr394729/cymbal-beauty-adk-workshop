"""Deterministic guardrails: code runs before the model and before tools, prompts only advise.

- mask_pii_before_model: emails and phone numbers never reach the model.
- enforce_dataset_allowlist_before_tool: raw SQL tools stay inside the allowed dataset (SELECT only).
- enforce_store_scope_before_tool: a tool can only act on the signed-in store unless the caller is a district manager.
- enforce_role_before_tool: coaching signals are for store and district managers only.
"""
from __future__ import annotations

import hashlib
import re
from contextvars import ContextVar
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import BaseTool, ToolContext
from google.genai import types

from agents.cymbal_store_ops.config import load_env_config
from agents.cymbal_store_ops.tools.sql_guard import SqlGuardError, assert_select_only

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_EVENT_READ_ONLY: ContextVar[str | None] = ContextVar("cymbal_event_read_only", default=None)
PHONE = re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)")


def redact(text: str) -> str:
    text = EMAIL.sub("[email redacted]", text)
    return PHONE.sub("[phone redacted]", text)


def mask_pii_before_model(callback_context: CallbackContext, llm_request: LlmRequest) -> types.LlmResponse | None:
    """Redact emails and phone numbers in user turns before they reach the model."""
    for content in llm_request.contents or []:
        if content.role != "user":
            continue
        for part in content.parts or []:
            if part.text:
                part.text = redact(part.text)
    return None


def set_event_read_only_before_model(callback_context: CallbackContext, llm_request: LlmRequest) -> None:
    """Determine the outer invocation's write boundary before request text redaction.

    Nested tools replace user_content; preserve the boundary with invocation/task-local context.
    Recompute once for each fresh root invocation so human follow-ups use normal confirmations.
    """
    state = callback_context.state
    if state.get("temp:event_guard_invocation") == callback_context.invocation_id:
        return None
    content = callback_context.user_content
    text = "\n".join(p.text or "" for p in (content.parts if content else []) or [] if p.text)
    expected = state.get("_event_initial_message_sha256")
    active = bool(expected and hashlib.sha256(text.encode()).hexdigest() == expected)
    state["temp:event_read_only"] = active
    # AgentTool creates a separate session and its service drops temp state. Async child calls
    # inherit task-local ContextVars, preserving the boundary without a persistent session lock.
    _EVENT_READ_ONLY.set(expected if active else None)
    state["temp:event_guard_invocation"] = callback_context.invocation_id
    return None


def enforce_dataset_allowlist_before_tool(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext) -> dict | None:
    """Fence the raw SQL tools to the allowed dataset before they run: SELECT-only statements inside it, and
    metadata calls (list_table_ids, get_table_info) only for it."""
    if tool.name not in ("execute_sql", "list_table_ids", "get_table_info"):
        return None
    cfg = load_env_config()
    project, dataset = cfg.project, cfg.bigquery.dataset
    prefix = f"{project}.{dataset}"
    if tool.name != "execute_sql":
        if args.get("project_id", project) != project or args.get("dataset_id", dataset) != dataset:
            return {"status": "ERROR", "error_details": f"blocked by policy: only {prefix} is available to this agent"}
        return None
    sql = args.get("query") or args.get("sql") or ""
    try:
        assert_select_only(sql, (prefix,))
    except SqlGuardError as e:
        return {"status": "ERROR", "error_details": f"blocked by policy before execution: {e}"}
    return None


MANAGER_ROLES = ("store_manager", "district_manager")
SCOPE_EXEMPT_TOOLS = ("identify_demo_user", "workshop_clock", "policy_lookup", "search_products", "get_product_details")


def enforce_store_scope_before_tool(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext) -> dict | None:
    """A tool acts on the signed-in store. A different store_id in the arguments is refused unless the caller is a
    district manager; no signed-in store at all is refused with the sign-in hint.

    ADK runs the before_tool_callback of the agent that owns the call, so this is attached to every LlmAgent that
    owns a store-scoped tool (root, the single_turn agents, the briefing branches, store_tasks, coaching);
    tests/unit/test_agent_tree.py fails if one is missed."""
    if tool.name in SCOPE_EXEMPT_TOOLS:
        return None
    state = tool_context.state
    home = state.get("user:store_id")
    if not home:
        return {"status": "ERROR", "error_details": "Store access requires the person to sign in. No store is signed in for this session; do not infer an identity."}
    requested = args.get("store_id")
    if requested and requested != home and state.get("user:role") != "district_manager":
        return {"status": "ERROR", "error_details": f"blocked by policy: this session is scoped to store {home}"}
    if args.get("city") and state.get("user:role") != "district_manager":
        return {"status": "ERROR", "error_details": f"blocked by policy: this session is scoped to store {home}; ask without a city, or sign in as a district manager"}
    return None


MANAGER_ONLY = {                       # tool name -> what needs a manager role (the message the model reads)
    "get_end_of_day_metrics": "end-of-day metrics need",
    "create_end_of_day_dashboard": "end-of-day reports need",
    "get_coaching_signals": "coaching signals need",
    "get_shrink_signals": "loss records need",
    "get_loss_controls": "loss-control records need",
    "get_task_history": "store task history needs",
    "create_store_task": "creating a store task needs",
    "delegate_task": "delegating a task needs",
    "store_tasks": "store tasks need",          # the task hand-off itself, when the root is the caller
}
DEVELOPMENT_AGENT = "associate_development"


def enforce_role_before_tool(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext) -> dict | None:
    """Managers only: legacy coaching signals, task creation/delegation and the store_tasks hand-off.
    Development transfers are available to associates; the personal tools enforce self-only access.
    A confirmation dialog answered by an associate is not a manager's approval."""
    initial_event_hash = tool_context.state.get("_event_initial_message_sha256")
    if (initial_event_hash or tool_context.state.get("temp:event_read_only")) and tool.name in {
        "create_store_task", "delegate_task", "complete_my_task", "report_my_task_blocker", "remember_work_preference",
    }:
        content = tool_context.user_content
        text = "\n".join(p.text or "" for p in (content.parts if content else []) or [] if p.text)
        if (tool_context.state.get("temp:event_read_only")
                or (initial_event_hash and _EVENT_READ_ONLY.get() == initial_event_hash)
                or hashlib.sha256(text.encode()).hexdigest() == initial_event_hash):
            return {"status": "ERROR", "code": "event_read_only",
                    "error_details": "Event analysis can recommend actions; a person must request any changes."}
    if tool.name == "identify_demo_user":
        requested = str(args.get("user_id", ""))
        current = tool_context.state.get("user:user_id")
        if current and requested != current:
            return {"status": "ERROR", "error_details": "Use the persona selector to change the signed-in person.", "code": "forbidden"}
        content = tool_context.user_content
        text = " ".join(p.text or "" for p in (content.parts if content else []) or [])
        if not requested or not re.search(r"(?<![\w-])" + re.escape(requested) + r"(?![\w-])", text, re.I):
            return {"status": "ERROR", "error_details": "Sign in before requesting store information. Do not infer an identity.", "code": "sign_in_required"}
    what = MANAGER_ONLY.get(tool.name)
    if what is None:
        return None
    role = tool_context.state.get("user:role")
    if role not in MANAGER_ROLES:
        return {"status": "ERROR", "error_details": f"blocked by policy: {what} a manager role (signed in as {role or 'nobody'})"}
    return None


FINISH_TASK = "finish_task"


def hand_back_after_model(callback_context: CallbackContext, llm_response: LlmResponse) -> LlmResponse | None:
    """For a task-mode agent: a plain final reply becomes finish_task(result=reply), so the agent always hands back.

    A task agent keeps the conversation until it calls finish_task, and the caller's function call stays unanswered
    until then. When store_tasks answered a rejected confirmation with a plain message, the next question landed on
    it and the root re-issued the unanswered store_tasks call: three confirmation dialogs for a question about
    hold times. store_tasks is one write or one explanation, so every plain reply is a hand-back; the manager reads
    the same words from the root."""
    content = llm_response.content
    if llm_response.partial or content is None or not content.parts:
        return None
    if any(part.function_call for part in content.parts):
        return None
    text = "".join(part.text or "" for part in content.parts if part.text and not part.thought).strip()
    if not text:
        return None
    handed = llm_response.model_copy()
    handed.content = types.Content(role="model", parts=[types.Part(
        function_call=types.FunctionCall(name=FINISH_TASK, args={"result": text}))])
    return handed
