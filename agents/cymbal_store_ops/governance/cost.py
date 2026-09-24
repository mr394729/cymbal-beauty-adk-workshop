"""Token usage and cost estimates from the agent's own execution trace.

The trace plugin (trace.py) records each model call's usage counts as a span. This module turns those spans into
per-turn and per-agent totals, applies prices the caller supplies, and projects a daily figure from a usage
assumption. Prices are never hard-coded: pass the current values from the pricing page.

The other cost line, BigQuery, comes from the job history: every tool query carries labels (ns, env, tool), so
bytes billed can be grouped by tool. `bigquery_jobs_by_tool` runs that query.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

USAGE_FIELDS = ("prompt_token_count", "candidates_token_count", "reasoning_token_count", "cached_token_count", "total_token_count")


@dataclass(frozen=True)
class Prices:
    """USD per one million tokens. Take the values from the model's pricing page; they change."""
    input_per_million: float
    output_per_million: float
    cached_input_per_million: float = 0.0
    reasoning_per_million: float | None = None   # None: reasoning tokens are billed as output

    def cost(self, usage: dict) -> float:
        prompt = usage.get("prompt_token_count") or 0
        cached = usage.get("cached_token_count") or 0
        output = usage.get("candidates_token_count") or 0
        reasoning = usage.get("reasoning_token_count") or 0
        reasoning_rate = self.output_per_million if self.reasoning_per_million is None else self.reasoning_per_million
        return ((prompt - cached) * self.input_per_million + cached * self.cached_input_per_million
                + output * self.output_per_million + reasoning * reasoning_rate) / 1_000_000


def load_sample(path: str | Path) -> list[dict]:
    """The committed sample: a list of turns, each with its spans."""
    return json.loads(Path(path).read_text())["turns"]


def model_spans(spans: list[dict]) -> list[dict]:
    return [s for s in spans if s.get("kind") == "model"]


def sum_usage(spans: list[dict]) -> dict:
    """Totals over the model spans. A field is None when any span lacks it, so a partial count is never shown as a total."""
    models = model_spans(spans)
    totals = {}
    for field in USAGE_FIELDS:
        values = [(m.get("usage") or {}).get(field) for m in models]
        totals[field] = sum(values) if models and all(v is not None for v in values) else None
    totals["model_calls"] = len(models)
    return totals


def usage_by_agent(spans: list[dict]) -> list[dict]:
    rows = {}
    for m in model_spans(spans):
        row = rows.setdefault(m["agent"], {"agent": m["agent"], "model_calls": 0, **{f: 0 for f in USAGE_FIELDS}})
        row["model_calls"] += 1
        for f in USAGE_FIELDS:
            row[f] += (m.get("usage") or {}).get(f) or 0
    return sorted(rows.values(), key=lambda r: -r["total_token_count"])


def turn_table(turns: list[dict], prices: Prices | None = None) -> list[dict]:
    rows = []
    for turn in turns:
        spans = turn["spans"]
        totals = sum_usage(spans)
        root = max((s.get("duration_ms") or 0) for s in spans if s.get("kind") == "agent" and s.get("parent_id") is None)
        row = {"turn": turn["turn"], "question": turn.get("question"), "seconds": round(root / 1000, 1),
               "tool_calls": sum(1 for s in spans if s.get("kind") == "tool"), **totals}
        if prices is not None:
            row["usd"] = round(prices.cost(totals), 4)
        rows.append(row)
    return rows


def daily_projection(turn_rows: list[dict], turns_per_user_per_day: float, users: int) -> dict:
    """A planning number, not a forecast: average cost per turn from the rows, times the usage assumption."""
    costs = [r["usd"] for r in turn_rows if "usd" in r]
    if not costs:
        raise ValueError("turn rows carry no usd column; pass prices to turn_table first")
    per_turn = sum(costs) / len(costs)
    per_day = per_turn * turns_per_user_per_day * users
    return {"average_usd_per_turn": round(per_turn, 4), "turns_per_day": int(turns_per_user_per_day * users),
            "usd_per_day": round(per_day, 2), "usd_per_30_days": round(per_day * 30, 2)}


BIGQUERY_JOBS_SQL = """
SELECT (SELECT value FROM UNNEST(labels) WHERE key = 'tool') AS tool,
       COUNT(*) AS jobs,
       ROUND(SUM(total_bytes_billed) / 1e6, 2) AS mb_billed,
       ROUND(AVG(TIMESTAMP_DIFF(end_time, start_time, MILLISECOND)), 0) AS avg_ms
FROM `{project}.region-{region}`.INFORMATION_SCHEMA.{view}
WHERE creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
  AND job_type = 'QUERY'
  AND EXISTS (SELECT 1 FROM UNNEST(labels) WHERE key = 'ns' AND value = @namespace)
GROUP BY tool
ORDER BY mb_billed DESC
"""


def bigquery_jobs_by_tool(project: str, namespace: str, *, region: str = "us", hours: int = 24,
                          scope: str = "user", on_demand_usd_per_tib: float | None = None) -> list[dict]:
    """Bytes billed per tool for one namespace from the job history. `scope="project"` reads JOBS_BY_PROJECT,
    which needs bigquery.jobs.listAll; the default reads your own jobs."""
    from google.cloud import bigquery

    view = "JOBS_BY_PROJECT" if scope == "project" else "JOBS_BY_USER"
    client = bigquery.Client(project=project)
    job = client.query(BIGQUERY_JOBS_SQL.format(project=project, region=region, view=view, hours=int(hours)),
                       job_config=bigquery.QueryJobConfig(
                           query_parameters=[bigquery.ScalarQueryParameter("namespace", "STRING", namespace)],
                           labels={"ns": namespace, "tool": "cost_notebook"}))
    rows = [dict(r) for r in job.result()]
    if on_demand_usd_per_tib is not None:
        for r in rows:
            r["usd_on_demand"] = round((r["mb_billed"] or 0) / 1e6 * on_demand_usd_per_tib, 4)
    return rows
