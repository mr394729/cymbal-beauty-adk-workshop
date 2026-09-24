from __future__ import annotations

from google.adk.agents import LlmAgent
from pydantic import BaseModel, Field

from agents.cymbal_store_ops.callbacks import enforce_store_scope_before_tool
from agents.cymbal_store_ops.models import thinking
from agents.cymbal_store_ops.prompts import load_prompt
from agents.cymbal_store_ops.tools.domain_tools import (
    check_store_stock,
    find_nearby_stock,
    get_bopis_demand,
    get_osa_exceptions,
    get_replenishment_status,
    get_task_status,
)
from agents.cymbal_store_ops.tools.inventory_context import get_inventory_context
from agents.cymbal_store_ops.tools.inventory_summary import (
    get_store_inventory_summary,
    list_store_inventory,
)
from agents.cymbal_store_ops.tools.operations_tools import concurrent_read, get_stock_location
from agents.cymbal_store_ops.tools.store_query import describe_store_data, query_store_data


class OsaQuery(BaseModel):
    request: str = Field(default="", description="The user’s question, including priorities, requested detail and hypothetical constraints")
    product_name: str | None = Field(default=None, description="Specific product name or exact SKU; omit for store/category inventory requests")
    store_id: str | None = Field(default=None, description="Another store's id, only when a district manager asks about it; "
                                                         "empty for the signed-in store")


def make_inventory_excellence() -> LlmAgent:
    """single_turn sub-agent: the manager's assistant calls it like a tool (a 'consultant'); no chat history.

    ADK docs:
      Single-turn mode: https://adk.dev/workflows/collaboration/#mode-configuration-and-behaviors
    Workshop pages: docs/patterns/02-agent-as-a-tool.md
    """
    return LlmAgent(
        name="inventory_excellence",
        description="Analyzes inventory decisions and dependencies across stock, reservations, pickup commitments, "
                    "locations, inbound supply and existing work. Returns specialist findings for the requested scope.",
        instruction=load_prompt("inventory_excellence"),
        tools=[concurrent_read(t) for t in [get_osa_exceptions, check_store_stock, find_nearby_stock, get_bopis_demand,
               get_replenishment_status, get_task_status, get_stock_location, get_store_inventory_summary,
               list_store_inventory, query_store_data]] + [get_inventory_context, describe_store_data],
        mode="single_turn",
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        input_schema=OsaQuery,
        include_contents="none",
        output_key="last_osa",
        before_tool_callback=enforce_store_scope_before_tool,
        generate_content_config=thinking(),
    )
