"""Pattern 1: a coordinator with a chat sub-agent (transfer) and a single_turn sub-agent (tool call).

The coordinator is this quickstart's router (agent.py). `coaching_specialist` is a team member: the conversation
moves to it, like `associate_development` in the store-ops tree. `stock_lookup` is an expert on call: the
coordinator calls it like a tool and keeps control, like `inventory_excellence`. Both prompts run as the demo manager.

ADK docs:
  Coordinator and dispatcher: https://adk.dev/workflows/patterns/#coordinator-and-dispatcher
  Single-turn mode: https://adk.dev/workflows/collaboration/#mode-configuration-and-behaviors
Workshop pages: docs/patterns/01-coordinator-and-dispatcher.md, docs/patterns/02-agent-as-a-tool.md
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _run import MANAGER_STATE, run  # noqa: E402

router = importlib.import_module("10-multi-agent-router.agent")

if __name__ == "__main__":
    print("== 01 coordinator vs single_turn")
    # a coaching question: transfer_to_agent -> coaching_specialist -> get_coaching_signals (its role gate reads user:role)
    run(router.make_root_agent(), "What coaching would help A-1007 with BOPIS picking?", MANAGER_STATE)
    # a lookup: stock_lookup is called as a tool with its input schema; the router keeps control and answers
    run(router.make_root_agent(), "Is Lumière Hydra Cream on the shelf in Naperville?", MANAGER_STATE)
