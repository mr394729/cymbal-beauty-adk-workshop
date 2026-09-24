from __future__ import annotations

from google.adk.agents import LlmAgent
from pydantic import BaseModel, Field

from agents.cymbal_store_ops.callbacks import enforce_store_scope_before_tool
from agents.cymbal_store_ops.models import thinking
from agents.cymbal_store_ops.prompts import load_prompt
from agents.cymbal_store_ops.tools.domain_tools import (
    get_shift_roster,
    get_traffic_and_backlog,
    workshop_clock,
)
from agents.cymbal_store_ops.tools.operations_tools import (
    concurrent_read,
    get_coverage_requirements,
)
from agents.cymbal_store_ops.tools.pickup_workload import get_pickup_workload
from agents.cymbal_store_ops.tools.store_query import describe_store_data, query_store_data


class CoverageQuery(BaseModel):
    request: str = Field(default="", description="The user’s question, including priorities, requested detail and hypothetical constraints")
    window_hours: int = Field(default=4, ge=1, le=12, description="How many hours ahead to plan coverage for")
    focus: str | None = Field(default=None, description="The work to cover, e.g. bopis, cash_wrap, backroom; empty means the biggest backlog")


def make_associate_orchestration() -> LlmAgent:
    """single_turn sub-agent: next best action for the floor from roster, traffic and BOPIS backlog.

    ADK docs:
      Single-turn mode: https://adk.dev/workflows/collaboration/#mode-configuration-and-behaviors
    Workshop pages: docs/patterns/02-agent-as-a-tool.md
    """
    return LlmAgent(
        name="associate_orchestration",
        description="Recommends who should move where and what to pick up next, from the shift roster, skills, "
                    "current tasks, traffic and the BOPIS backlog. Store scope comes from the session.",
        instruction=load_prompt("associate_orchestration"),
        tools=[workshop_clock, get_pickup_workload, describe_store_data,
               *[concurrent_read(t) for t in [get_traffic_and_backlog, get_shift_roster, get_coverage_requirements, query_store_data]]],
        mode="single_turn",
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        input_schema=CoverageQuery,
        include_contents="none",
        output_key="last_coverage",
        before_tool_callback=enforce_store_scope_before_tool,
        generate_content_config=thinking(),
    )
