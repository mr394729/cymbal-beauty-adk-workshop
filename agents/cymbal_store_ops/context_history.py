"""Keep completed consultant summaries without replaying their private transcript.

This changes only the root's outgoing model request. Session events, tool results,
confirmation history and execution traces remain authoritative and untouched.
"""
from __future__ import annotations

import json

from google.adk.flows.llm_flows._fencing import _present_other_agent_message

CONSULTANTS = frozenset({"inventory_excellence", "associate_orchestration", "loss_prevention"})
ROOT = "store_manager_agent"


def _fingerprint(content):
    return json.dumps(content.model_dump(mode="json", exclude_none=True), sort_keys=True)


def _successful(response):
    """A completed delegate result, never a pending/failed/confirmation response."""
    if not isinstance(response, dict) or not response.get("result"):
        return False
    if any(response.get(key) for key in ("error", "error_details", "error_message")):
        return False
    return str(response.get("status", "SUCCESS")).upper() in {"SUCCESS", "OK"}


def prune_completed_consultant_history(callback_context, llm_request):
    """Root before-model callback; fail closed whenever provenance is ambiguous.

    ADK exposes consultant branches as ``agent@delegation_call_id``. On a later
    turn those events can reappear as quoted user-role messages even though the
    consultant's hand-back response is already retained. Match the original
    author, invocation, delegation id and branch, then the *exact* ADK-rendered
    content. Never identify a user message merely by its marker text.
    """
    context = callback_context.get_invocation_context()
    if context.agent.name != ROOT:
        return
    # Compacted history has different provenance. Leave it to ADK's compactor.
    events = context.session.events
    if any(event.actions and event.actions.compaction for event in events):
        return
    retained = {
        (part.function_response.name, part.function_response.id)
        for content in llm_request.contents for part in content.parts or []
        if part.function_response and part.function_response.id
        and part.function_response.name in CONSULTANTS
        and _successful(part.function_response.response)
    }
    if not retained:
        return
    delegations = set()
    completed = set()
    for event in events:
        if event.author != ROOT or event.partial or not event.content:
            continue
        for part in event.content.parts or []:
            call = part.function_call
            if call and call.name in CONSULTANTS and call.id:
                delegations.add((event.invocation_id, call.name, call.id))
            response = part.function_response
            if response and (response.name, response.id) in retained and _successful(response.response):
                key = (event.invocation_id, response.name, response.id)
                if key in delegations:
                    completed.add(key)
    if not completed:
        return
    # Even a byte-for-byte user copy of framework text stays a user message.
    protected = {_fingerprint(event.content) for event in events
                 if event.author == "user" and event.content}
    if context.user_content:
        protected.add(_fingerprint(context.user_content))
    removable = set()
    for invocation, author, call_id in completed:
        branch = f"{author}@{call_id}"
        sources = [event for event in events if event.author == author
                   and event.invocation_id == invocation and event.branch == branch]
        if not sources:
            continue
        # Never prune failed/incomplete tool work or any confirmation transcript.
        unsafe = False
        for event in sources:
            if event.error_code or event.error_message:
                unsafe = True
            for part in (event.content.parts if event.content else []) or []:
                if part.function_call and part.function_call.name == "adk_request_confirmation":
                    unsafe = True
                response = part.function_response
                if response and (response.name == "adk_request_confirmation" or
                                 str(response.response.get("status", "")).upper() in
                                 {"ERROR", "FAILED", "PENDING_CONFIRMATION", "CANCELLED"} or
                                 any(response.response.get(key) for key in
                                     ("error", "error_details", "error_message"))):
                    unsafe = True
        if unsafe:
            continue
        for event in sources:
            if event.partial or not event.content:
                continue
            quoted = _present_other_agent_message(event)
            if quoted and quoted.content:
                fingerprint = _fingerprint(quoted.content)
                if fingerprint not in protected:
                    removable.add(fingerprint)
    if removable:
        llm_request.contents = [content for content in llm_request.contents
                                if _fingerprint(content) not in removable]
