from __future__ import annotations

from google.adk.agents import LlmAgent
from pydantic import BaseModel, Field

from agents.cymbal_store_ops.callbacks import enforce_store_scope_before_tool
from agents.cymbal_store_ops.models import thinking
from agents.cymbal_store_ops.prompts import load_prompt
from agents.cymbal_store_ops.tools.domain_tools import (
    get_sales_pattern,
    get_shrink_signals,
    get_task_history,
    search_products,
)
from agents.cymbal_store_ops.tools.operations_tools import (
    concurrent_read,
    get_loss_controls,
    get_loss_reconciliation,
)
from agents.cymbal_store_ops.tools.store_query import describe_store_data, query_store_data


class ShrinkQuery(BaseModel):
    request: str = Field(default="", description="The user’s question, including priorities, requested detail and hypothetical constraints")
    product_name: str | None = Field(default=None, description="Product name, or empty for the whole store")
    days: int = Field(default=14, ge=1, le=90, description="Look-back window in days")


def make_loss_prevention() -> LlmAgent:
    """single_turn sub-agent: shrink and damage pattern review, recommendation-only, never about a person.

    ADK docs:
      Single-turn mode: https://adk.dev/workflows/collaboration/#mode-configuration-and-behaviors
    Workshop pages: docs/patterns/02-agent-as-a-tool.md
    """
    return LlmAgent(
        name="loss_prevention",
        description="Reviews shrink and damage signals (incidents, returns, adjustments) with sales and task history "
                    "and recommends investigation or monitoring. Never names individuals. Store scope comes from the session.",
        instruction=load_prompt("loss_prevention"),
        tools=[describe_store_data, *[concurrent_read(t) for t in [search_products, get_shrink_signals, get_sales_pattern,
               get_task_history, get_loss_controls, get_loss_reconciliation, query_store_data]]],
        mode="single_turn",
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        input_schema=ShrinkQuery,
        include_contents="none",
        output_key="last_shrink",
        before_tool_callback=enforce_store_scope_before_tool,
        generate_content_config=thinking(),
    )
