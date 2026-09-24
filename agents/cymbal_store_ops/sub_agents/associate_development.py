from __future__ import annotations

from google.adk.agents import LlmAgent

from agents.cymbal_store_ops.callbacks import (
    enforce_role_before_tool,
    enforce_store_scope_before_tool,
    mask_pii_before_model,
)
from agents.cymbal_store_ops.chat_reply import ChatReply
from agents.cymbal_store_ops.models import thinking
from agents.cymbal_store_ops.prompts import load_prompt
from agents.cymbal_store_ops.tools.operations_tools import concurrent_read, get_learning_options
from agents.cymbal_store_ops.tools.personal_tools import get_coaching_context


def make_associate_development() -> LlmAgent:
    """Chat sub-agent (transfer): coaching summaries and training suggestions; refuses HR decisions.

    ADK docs:
      Coordinator and dispatcher: https://adk.dev/workflows/patterns/#coordinator-and-dispatcher
    Workshop pages: docs/patterns/01-coordinator-and-dispatcher.md
    """
    return LlmAgent(
        name="associate_development",
        description="Summarises an associate's development opportunities from coaching signals and suggests training. "
                    "Makes no HR or disciplinary decisions.",
        instruction=load_prompt("associate_development"),
        output_schema=ChatReply,
        disallow_transfer_to_peers=True,
        tools=[concurrent_read(t) for t in [get_coaching_context, get_learning_options]],
        before_model_callback=mask_pii_before_model,
        before_tool_callback=[enforce_store_scope_before_tool, enforce_role_before_tool],
        generate_content_config=thinking(),
    )
