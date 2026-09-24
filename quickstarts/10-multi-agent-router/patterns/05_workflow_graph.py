"""Pattern 5: the ADK 2.x Workflow graph. Code routes an exception event (osa | coverage | shrink) to its agent, not a
model; `classify_event` fails once on purpose (a flaky feed) so its retry_config shows. In production the event
comes from a trigger (Pub/Sub, Eventarc), not a chat message.

ADK docs:
  Graph-based agent workflows: https://adk.dev/graphs/
Workshop pages: docs/patterns/08-workflow-graph.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _run import MANAGER_STATE, run  # noqa: E402
from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.events import Event  # noqa: E402
from google.adk.workflow import START, RetryConfig, Workflow, node  # noqa: E402

from agents.cymbal_store_ops.config import load_env_config  # noqa: E402
from agents.cymbal_store_ops.models import workshop_model  # noqa: E402
from agents.cymbal_store_ops.tools import domain_tools as T  # noqa: E402

cfg = load_env_config()
ATTEMPTS = {"n": 0}


@node(retry_config=RetryConfig(max_attempts=2, initial_delay=0.5, exceptions=[TimeoutError]))
def classify_event(node_input) -> Event:
    """Parse the event and emit its type as the route. Only a TimeoutError is retried; a bad event fails loudly."""
    ATTEMPTS["n"] += 1
    if ATTEMPTS["n"] == 1:
        print("  [retry] classify_event attempt 1: TimeoutError from the event feed; retry_config runs it again")
        raise TimeoutError("event feed timed out")
    event = json.loads("".join(p.text or "" for p in node_input.parts))
    if event.get("type") not in ("osa", "coverage", "shrink"):
        raise ValueError(f"unroutable exception event: {event}")
    return Event(output=json.dumps(event), route=event["type"], state={"event_type": event["type"]})


def handler(name: str, tools: list, ask: str) -> LlmAgent:
    return LlmAgent(name=name, model=workshop_model(cfg), tools=tools, output_key="resolution",
                    instruction=f"The message is a store exception event. {ask} Reply in two lines: the evidence "
                                "(ids and counts from the tools) and the tool's recommendation.")


osa = handler("osa_handler", [T.check_store_stock, T.get_bopis_demand], "Call check_store_stock and get_bopis_demand for its product_id.")
coverage = handler("coverage_handler", [T.get_traffic_and_backlog, T.get_shift_roster], "Call get_traffic_and_backlog and get_shift_roster with its focus and window_hours.")
shrink = handler("shrink_handler", [T.get_shrink_signals], "Call get_shrink_signals for its product_id over 14 days.")


def notify_manager(event_type: str, resolution: str) -> str:
    """A plain function is a node too; its parameters bind from state (event_type from intake, resolution from the agent)."""
    return f"[{event_type.upper()}] {resolution}"


exception_router = Workflow(name="exception_router", edges=[
    (START, classify_event, {"osa": osa, "coverage": coverage, "shrink": shrink}, notify_manager)])

if __name__ == "__main__":
    print("== 05 workflow graph: exception routing")
    for event in ({"type": "osa", "product_id": "P-0101"}, {"type": "coverage", "focus": "bopis", "window_hours": 2},
                  {"type": "shrink", "product_id": "P-0420"}):
        run(exception_router, json.dumps(event), MANAGER_STATE)
