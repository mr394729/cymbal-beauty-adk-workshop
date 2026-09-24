"""Preconditions for evaluating against your live dataset.

The goldens describe the fixture: for example, no task is open for Lumière Hydra Cream. The approve and delegate steps
(the tools notebook, scripts/smoke_local.py) really write to `store_tasks`, so an evaluation run after them would compare a correct
answer ("a backroom check is already open") with a reference that is no longer true, and fail for the wrong reason.
Writes are recognisable: fixture rows have no task_key and no delegation_key. Refuse loudly instead of scoring.
"""
from __future__ import annotations

WRITES_SQL = "SELECT COUNT(*) AS n FROM `{table}` WHERE task_key IS NOT NULL OR delegation_key IS NOT NULL"


def lab_writes(cfg) -> int:
    """How many store_tasks rows an approve or delegate step wrote since the last load."""
    from google.cloud import bigquery

    table = f"{cfg.project}.{cfg.bigquery.dataset}.store_tasks"
    client = bigquery.Client(project=cfg.project, location=cfg.bigquery.location)
    job = client.query(WRITES_SQL.format(table=table),
                       job_config=bigquery.QueryJobConfig(labels={**cfg.bigquery.job_labels, "adk_tool": "eval_precondition"}))
    return int(next(iter(job.result())).n)


def assert_fixture_state(cfg=None) -> None:
    """Raise with the fix when store_tasks holds lab writes; return quietly when it is at fixture state."""
    if cfg is None:
        from agents.cymbal_store_ops.config import load_env_config

        cfg = load_env_config()
    n = lab_writes(cfg)
    if n:
        raise RuntimeError(
            f"{n} row(s) in {cfg.bigquery.dataset}.store_tasks were written by an approve or delegate step (the tools notebook or "
            "scripts/smoke_local.py). The goldens describe the fixture, where no task is open for the hero product, so "
            "the scores would be wrong. Run `bash data/load.sh --env dev --tables store_tasks`, then run the evaluation again.")
