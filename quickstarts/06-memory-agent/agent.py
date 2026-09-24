"""Quickstart 06 — memory agent.

A store manager's huddle assistant that remembers how the manager likes the start of the day. Two kinds of
remembering. `user:` state (huddle time, focus areas) survives sessions on any persistent session service and is
injected into the instruction with `{user:huddle_time?}`. Memory Bank (Agent Runtime) is long-term memory of past
conversations, searched by `preload_memory` before every turn and by `load_memory` on demand; locally `adk web`
provides an in-memory service, and `--memory_service_uri=agentengine://<engine id>` switches to Memory Bank with no
code change. The huddle facts come from the store operations tools, scoped to `user:store_id`.
"""
from __future__ import annotations

import re
import warnings

warnings.filterwarnings("ignore", message=r".*\[EXPERIMENTAL\].*", module=r"google\.adk.*")

from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.agents.callback_context import CallbackContext  # noqa: E402
from google.adk.apps import App  # noqa: E402
from google.adk.tools import ToolContext, load_memory, preload_memory  # noqa: E402

from agents.cymbal_store_ops.config import load_env_config  # noqa: E402
from agents.cymbal_store_ops.models import workshop_model  # noqa: E402
from agents.cymbal_store_ops.tools.domain_tools import (  # noqa: E402
    get_osa_exceptions,
    get_shrink_signals,
    get_traffic_and_backlog,
    identify_demo_user,
)

FOCUS_AREAS = ("bopis", "on_shelf", "shrink")

INSTRUCTION = """You prepare a Cymbal Beauty store manager's start-of-day huddle and remember how they like it.
Signed-in store: {user:store_id?}. Remembered — huddle time: {user:huddle_time?}; focus areas, in order: {user:focus_areas?}.
- If no store is signed in, ask for the manager's demo id (for example U-M014) and call identify_demo_user.
- When the manager states a huddle time or what they want covered first, call remember_preferences so every
  later session starts from it. Past conversations may also come back from memory; use load_memory when the
  manager refers to something said before.
- To prepare the huddle, cover the focus areas in the remembered order: bopis with get_traffic_and_backlog,
  on_shelf with get_osa_exceptions (limit 3), shrink with get_shrink_signals. With nothing remembered, ask once.
- Answer in at most four sentences: what you remembered (if anything changed), then the facts for each focus
  area with the ids and counts from the tools. Never invent a number."""


def remember_preferences(tool_context: ToolContext, huddle_time: str = "", focus_areas: list[str] | None = None) -> dict:
    """Save the manager's huddle preferences for every future session.

    Args:
        huddle_time: 24-hour HH:MM, e.g. "08:45". Empty = keep the remembered one.
        focus_areas: what to cover first, in order, from: bopis, on_shelf, shrink. Empty = keep the remembered ones.
    """
    if not huddle_time and not focus_areas:
        return {"status": "ERROR", "error_details": "give a huddle_time, focus_areas, or both"}
    if huddle_time and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", huddle_time):
        return {"status": "ERROR", "error_details": f"huddle_time {huddle_time!r} must be 24-hour HH:MM, like 08:45"}
    unknown = [f for f in focus_areas or [] if f not in FOCUS_AREAS]
    if unknown:
        return {"status": "ERROR", "error_details": f"unknown focus areas {unknown}; choose from {list(FOCUS_AREAS)}"}
    if huddle_time:
        tool_context.state["user:huddle_time"] = huddle_time
    if focus_areas:
        tool_context.state["user:focus_areas"] = ", ".join(dict.fromkeys(focus_areas))
    return {"status": "SUCCESS", "rows": [{"huddle_time": tool_context.state.get("user:huddle_time", ""),
                                          "focus_areas": tool_context.state.get("user:focus_areas", "")}]}


async def save_session_to_memory(callback_context: CallbackContext) -> None:
    """After each turn, add the session to long-term memory (memory_service.add_session_to_memory, the
    documented ingestion call). With the in-memory service this lives for the process; with Memory Bank it persists."""
    ctx = callback_context._invocation_context  # noqa: SLF001  (the runner's context: session + memory service)
    if ctx.memory_service is not None:
        await ctx.memory_service.add_session_to_memory(ctx.session)


def make_root_agent() -> LlmAgent:
    cfg = load_env_config()
    return LlmAgent(
        name="memory_agent",
        model=workshop_model(cfg),
        description="Prepares a store manager's huddle and remembers their huddle time and focus areas across sessions.",
        instruction=INSTRUCTION,
        tools=[preload_memory, load_memory, identify_demo_user, remember_preferences,
               get_traffic_and_backlog, get_osa_exceptions, get_shrink_signals],
        after_agent_callback=save_session_to_memory,
    )


def create_app() -> App:
    return App(name="memory_agent", root_agent=make_root_agent())


app = create_app()
root_agent = app.root_agent
