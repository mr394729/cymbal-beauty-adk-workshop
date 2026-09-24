"""Cymbal Beauty store operations — the workshop's running example (the agentic store manager).

Tree (ADK 2.x):
  store_manager_agent (chat root)
  ├── daily_briefing            AgentTool → SequentialAgent[ParallelAgent(3 signal branches) → plan_writer(ActionPlan)]
  ├── inventory_excellence      single_turn  → called as a tool (consultant, no history)
  ├── associate_orchestration   single_turn  → called as a tool
  ├── loss_prevention           single_turn  → called as a tool (recommendation-only)
  ├── associate_development     chat sub-agent → transfer_to_agent (team member, full history)
  └── store_tasks               task         → the only write path, with human confirmation, hands back
  + get_guest_feedback on the root (a manager asks about feedback directly, not only through the briefing)
  + policy_lookup (Vertex AI Search over the store SOPs) only when SOP_DATA_STORE is set
  + Model Armor prompt screening before the coordinator's model call only when MODEL_ARMOR_TEMPLATE is set

Exports `root_agent` (for `adk web`/`adk eval`) and `app` (plugins + resumability, used by deploy).

ADK docs:
  Coordinator and dispatcher: https://adk.dev/workflows/patterns/#coordinator-and-dispatcher
  Single-turn mode: https://adk.dev/workflows/collaboration/#mode-configuration-and-behaviors
  Parallel fan-out and gather: https://adk.dev/workflows/patterns/#parallel-fan-out-and-gather
  Hierarchical task decomposition: https://adk.dev/workflows/patterns/#hierarchical-task-decomposition
  Human-in-the-loop: https://adk.dev/workflows/patterns/#human-in-the-loop
Workshop pages: docs/patterns/01-coordinator-and-dispatcher.md, docs/patterns/02-agent-as-a-tool.md, docs/patterns/04-parallel-fan-out.md, docs/patterns/06-hierarchical-task-decomposition.md, docs/patterns/07-human-in-the-loop.md
"""
# ruff: noqa: E402
from __future__ import annotations

import os
import warnings

warnings.filterwarnings("ignore", message=r".*\[EXPERIMENTAL\].*", module=r"google\.adk.*")

from google.adk.agents import LlmAgent
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps import App
from google.adk.apps.app import ResumabilityConfig
from google.adk.plugins.logging_plugin import LoggingPlugin
from google.genai import types

from agents.cymbal_store_ops.callbacks import (
    enforce_role_before_tool,
    enforce_store_scope_before_tool,
    mask_pii_before_model,
    set_event_read_only_before_model,
)
from agents.cymbal_store_ops.chat_reply import ChatReply, ChatReplyPlugin
from agents.cymbal_store_ops.config import load_env_config
from agents.cymbal_store_ops.context_history import prune_completed_consultant_history
from agents.cymbal_store_ops.governance.model_armor import (
    configured_template,
    make_screen_before_model,
)
from agents.cymbal_store_ops.mcp_catalog import READS
from agents.cymbal_store_ops.mcp_connection import make_operational_mcp_toolset, mcp_configured
from agents.cymbal_store_ops.models import thinking, workshop_model
from agents.cymbal_store_ops.plugins import IngressRedactionPlugin, LoopGuardPlugin
from agents.cymbal_store_ops.prompts import load_prompt
from agents.cymbal_store_ops.sub_agents.associate_development import (
    make_associate_development,
)
from agents.cymbal_store_ops.sub_agents.associate_orchestration import (
    make_associate_orchestration,
)
from agents.cymbal_store_ops.sub_agents.daily_briefing import make_daily_briefing_tool
from agents.cymbal_store_ops.sub_agents.inventory_excellence import (
    make_inventory_excellence,
)
from agents.cymbal_store_ops.sub_agents.loss_prevention import make_loss_prevention
from agents.cymbal_store_ops.sub_agents.store_tasks import make_store_tasks
from agents.cymbal_store_ops.tools.domain_tools import (
    get_bopis_demand,
    get_guest_feedback,
    get_product_details,
    get_replenishment_status,
    get_shrink_signals,
    get_task_history,
    identify_demo_user,
    search_products,
    workshop_clock,
)
from agents.cymbal_store_ops.tools.end_of_day import (
    create_end_of_day_dashboard,
    get_end_of_day_metrics,
)
from agents.cymbal_store_ops.tools.inventory_context import get_inventory_context
from agents.cymbal_store_ops.tools.inventory_summary import (
    get_product_stock,
    get_store_inventory_summary,
    list_store_inventory,
)
from agents.cymbal_store_ops.tools.operations_tools import (
    concurrent_read,
    get_guest_product_options,
    get_loss_controls,
    get_merchandising_work,
)
from agents.cymbal_store_ops.tools.personal_tools import (
    complete_my_task,
    get_my_work,
    report_my_task_blocker,
)
from agents.cymbal_store_ops.tools.policy_lookup import (
    configured_data_store,
    make_policy_lookup,
)
from agents.cymbal_store_ops.tools.report_delivery import (
    deliver_store_report,
    describe_store_data,
    query_store_data,
)
from agents.cymbal_store_ops.tools.work_memory import (
    configured_memory_engine,
    make_work_memory_tools,
)
from agents.cymbal_store_ops.trace import ExecutionTracePlugin


def make_root_agent() -> LlmAgent:
    """Factory: every call builds a fresh tree (sub-agents can only have one parent). Sub-agents inherit the model."""
    cfg = load_env_config()
    model = workshop_model(cfg)
    tools = [identify_demo_user, workshop_clock, concurrent_read(get_my_work), complete_my_task, report_my_task_blocker,
             concurrent_read(get_merchandising_work), concurrent_read(get_guest_product_options),
             concurrent_read(get_guest_feedback), concurrent_read(search_products), concurrent_read(get_product_details),
             make_daily_briefing_tool(model),
             describe_store_data, concurrent_read(query_store_data), deliver_store_report,
             concurrent_read(get_store_inventory_summary), concurrent_read(list_store_inventory),
             concurrent_read(get_product_stock), concurrent_read(get_bopis_demand), concurrent_read(get_replenishment_status),
             get_inventory_context, concurrent_read(get_shrink_signals), concurrent_read(get_loss_controls),
             concurrent_read(get_task_history), get_end_of_day_metrics, create_end_of_day_dashboard]
    sop_data_store = configured_data_store()   # None when SOP_DATA_STORE is unset; loud when it is not yours
    armor = configured_template()             # None when MODEL_ARMOR_TEMPLATE is unset (notebook 06 creates one)
    screening = [make_screen_before_model(*armor)] if armor else []
    if sop_data_store:
        tools.append(make_policy_lookup(sop_data_store))
    memory_engine = configured_memory_engine()
    if memory_engine:
        tools.extend(make_work_memory_tools(memory_engine))
    root = LlmAgent(
        name="store_manager_agent",
        model=model,
        description="Cymbal Beauty store operations assistant: inventory browsing and availability, "
                    "store priorities, staffing and pickup, loss controls, learning and reviewed store tasks.",
        instruction=load_prompt("root"),
        output_schema=ChatReply,
        tools=tools,
        sub_agents=[make_inventory_excellence(), make_associate_orchestration(), make_loss_prevention(),
                    make_associate_development(), make_store_tasks()],
        generate_content_config=thinking(),
        before_model_callback=[set_event_read_only_before_model, mask_pii_before_model, prune_completed_consultant_history,
                               *screening],
        before_tool_callback=[enforce_store_scope_before_tool, enforce_role_before_tool],
    )
    if mcp_configured():
        # Deployed: every store record read goes through the MCP server, for the coordinator and each specialist.
        for agent in (root, *root.sub_agents):
            serve_reads_through_mcp(agent)
    return root


def _tool_name(tool) -> str:
    return getattr(tool, "name", None) or getattr(tool, "__name__", "")


def serve_reads_through_mcp(agent: LlmAgent) -> None:
    """Replace the agent's local store reads with the same tools served by the MCP server (same names and arguments)."""
    reads = [name for name in map(_tool_name, agent.tools) if name in READS]
    if reads:
        agent.tools = [tool for tool in agent.tools if _tool_name(tool) not in READS]
        agent.tools.append(make_operational_mcp_toolset(reads))


def create_app(log_events: bool = True) -> App:
    """log_events=False leaves out the plugin that prints every event to stdout (for Cloud Logging); notebooks use it."""
    plugins = [IngressRedactionPlugin(), LoopGuardPlugin(), ExecutionTracePlugin(), ChatReplyPlugin()]
    if log_events:
        plugins.append(LoggingPlugin())
    return App(
        name="cymbal_store_ops",
        root_agent=make_root_agent(),
        plugins=plugins,
        resumability_config=ResumabilityConfig(is_resumable=True),
        # Cache larger repeated prefixes; short requests avoid a separate cache-creation round trip.
        context_cache_config=ContextCacheConfig(
            min_tokens=16384, ttl_seconds=1800, cache_intervals=10,
            create_http_options=types.HttpOptions(timeout=5000, retry_options=types.HttpRetryOptions(attempts=1)),
        ),
    )


app = create_app()
# A process that is about to serve traffic warms the data backend while it starts, so the BigQuery client, the
# dataset lookup and the first query are not paid for inside someone's first question. Off by default: importing
# this module in a test or a lint run must not reach BigQuery. `uv run adk web agents --port 8000`, `uv run python frontend/server.py --target local --port 8080` and every deployed
# engine set it (deployment/deploy.py puts it in env_vars).
if os.environ.get("STORE_OPS_PREWARM") == "1":
    from agents.cymbal_store_ops.tools.data_backend import prewarm

    prewarm()

root_agent = app.root_agent
