from __future__ import annotations

from google.adk.agents import LlmAgent

from agents.cymbal_store_ops.callbacks import (
    enforce_role_before_tool,
    enforce_store_scope_before_tool,
    hand_back_after_model,
)
from agents.cymbal_store_ops.models import thinking
from agents.cymbal_store_ops.prompts import load_prompt
from agents.cymbal_store_ops.tools.domain_tools import (
    create_store_task,
    delegate_task,
    get_task_status,
    workshop_clock,
)


def make_store_tasks() -> LlmAgent:
    """task sub-agent: the only write path. Creates or delegates a task after the manager confirms, then hands back.

    The confirmation lives inside the two write tools (tool_context.request_confirmation), so the dialog names the
    task, product, assignee and note being approved rather than a generic "approve this tool call".

    Two guardrails in code: the write tools refuse any role but a manager (an associate answering the dialog is
    not an approval), and a plain reply is turned into finish_task so the agent always hands back, also after a
    rejection: a task agent that answers in prose keeps the conversation, and the root's unanswered call to it
    is re-issued on the next question.

    ADK docs:
      Human-in-the-loop: https://adk.dev/workflows/patterns/#human-in-the-loop
      Advanced tool confirmation: https://adk.dev/tools-custom/confirmation/#advanced-confirmation
    Workshop pages: docs/patterns/07-human-in-the-loop.md
    """
    return LlmAgent(
        name="store_tasks",
        description="Creates a store task (backroom check, replenish, cycle count, coverage move, investigation, coaching, "
                    "planogram or signage fix) or delegates an open one to an associate, after the manager confirms.",
        instruction=load_prompt("store_tasks"),
        tools=[workshop_clock, get_task_status, create_store_task, delegate_task],
        mode="task",
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        before_tool_callback=[enforce_store_scope_before_tool, enforce_role_before_tool],
        after_model_callback=hand_back_after_model,
        generate_content_config=thinking(),
    )
