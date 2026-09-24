"""Pattern 3: ParallelAgent fan-out over three signal agents, then one gather agent reads their output_keys.

The same shape as `daily_briefing` in the store-ops tree. The built version keeps the branch results in `temp:`
state (gone after the invocation) and gives the writer `output_schema=ActionPlan`; this one prints plain text.

ADK docs:
  Parallel fan-out and gather: https://adk.dev/workflows/patterns/#parallel-fan-out-and-gather
Workshop pages: docs/patterns/04-parallel-fan-out.md
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _run import MANAGER_STATE, run  # noqa: E402
from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent  # noqa: E402

from agents.cymbal_store_ops.config import load_env_config  # noqa: E402
from agents.cymbal_store_ops.models import workshop_model  # noqa: E402
from agents.cymbal_store_ops.tools.domain_tools import (  # noqa: E402
    get_osa_exceptions,
    get_shift_roster,
    get_shrink_signals,
    get_traffic_and_backlog,
)

cfg = load_env_config()


def branch(name: str, tools: list, ask: str, output_key: str) -> LlmAgent:
    return LlmAgent(name=name, model=workshop_model(cfg), tools=tools, include_contents="none", output_key=output_key,
                    instruction=ask + " Reply in at most three lines with the ids and counts from the tools. No prose.")


signals = ParallelAgent(name="signals", sub_agents=[
    branch("briefing_inventory", [get_osa_exceptions], "Call get_osa_exceptions with limit 3.", "inventory_signals"),
    branch("briefing_coverage", [get_traffic_and_backlog, get_shift_roster],
           "Call get_traffic_and_backlog for 4 hours and get_shift_roster with focus bopis and window_hours 2.", "coverage_signals"),
    branch("briefing_shrink", [get_shrink_signals], "Call get_shrink_signals for 14 days; keep the products to investigate.", "shrink_signals"),
])
plan_writer = LlmAgent(
    name="plan_writer", model=workshop_model(cfg),
    instruction="Inventory:\n{inventory_signals}\n\nCoverage:\n{coverage_signals}\n\nShrink:\n{shrink_signals}\n\n"
                "Write the store manager's three priorities for this morning, most urgent first, one line each with its "
                "evidence (ids and counts). Nothing without a signal behind it.")
daily_briefing = SequentialAgent(name="daily_briefing", sub_agents=[signals, plan_writer])

if __name__ == "__main__":
    print("== 03 parallel fan-out / gather")
    run(daily_briefing, "Give me my start-of-day plan.", MANAGER_STATE)
