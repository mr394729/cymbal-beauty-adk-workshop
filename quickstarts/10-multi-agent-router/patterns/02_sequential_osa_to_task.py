"""Pattern 2: SequentialAgent. osa_triage writes {osa_finding}; task_drafter reads it and drafts a store task.

The drafter sees none of the triage conversation (include_contents="none"): state is the only handoff. It drafts
and does not create; in the store-ops tree the write is `store_tasks`, behind a confirmation.

ADK docs:
  Sequential pipeline: https://adk.dev/workflows/patterns/#sequential-pipeline
Workshop pages: docs/patterns/03-sequential-pipeline.md
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _run import MANAGER_STATE, run  # noqa: E402
from google.adk.agents import LlmAgent, SequentialAgent  # noqa: E402

from agents.cymbal_store_ops.config import load_env_config  # noqa: E402
from agents.cymbal_store_ops.models import workshop_model  # noqa: E402
from agents.cymbal_store_ops.tools.domain_tools import (  # noqa: E402
    get_bopis_demand,
    get_osa_exceptions,
    get_task_status,
)

cfg = load_env_config()
triage = LlmAgent(
    name="osa_triage", model=workshop_model(cfg), tools=[get_osa_exceptions, get_bopis_demand], output_key="osa_finding",
    instruction="Call get_osa_exceptions with limit 3 for the signed-in store, then get_bopis_demand for the first "
                "exception's product. Write three lines: product id and name; on-shelf / backroom / on-hand against the "
                "reorder point and the pending BOPIS orders; the tool's recommendation. Only numbers from the tools.")
drafter = LlmAgent(
    name="task_drafter", model=workshop_model(cfg), tools=[get_task_status], include_contents="none",
    instruction="OSA finding:\n{osa_finding}\n\nCall get_task_status for that product so you never draft a duplicate. "
                "If no task is open, draft one store task as three lines: task_type (the recommendation), product_id, "
                "and a one-sentence note citing the counts. Say it is a draft for the manager to approve; create nothing.")
pipeline = SequentialAgent(name="osa_to_task", sub_agents=[triage, drafter])

if __name__ == "__main__":
    print("== 02 sequential: OSA triage -> task draft")
    run(pipeline, "Triage this morning's shelf gaps and draft the first task.", MANAGER_STATE, show=("osa_finding",))
