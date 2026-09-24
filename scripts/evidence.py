"""Governance evidence: who ran what against the workshop data, straight from the platform's own records.

    uv run python scripts/evidence.py [--hours 1] [--limit 20] [--scope user|project]

BigQuery: INFORMATION_SCHEMA.JOBS_BY_USER (the default: the jobs the current credential submitted, which is what
`roles/bigquery.user` may list) or, with `--scope project`, JOBS_BY_PROJECT (every identity's jobs, the deployed
engines' included; needs `bigquery.jobs.listAll`, which the attendee grants do not carry), for the region, filtered
to jobs carrying the namespace label and showing the agent's labels (`adk_agent`, `env`, `tool` from the backend, or
the `adk-bigquery-tool` label the ADK toolset adds on its own), with referenced_tables and bytes processed. Note
that Dataplex lineage is not emitted for plain SELECTs, so JOBS.referenced_tables is the read evidence on BigQuery.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

VIEWS = {"user": "JOBS_BY_USER", "project": "JOBS_BY_PROJECT"}   # scope -> INFORMATION_SCHEMA view

BQ_SQL = """
SELECT
  FORMAT_TIMESTAMP('%H:%M:%S', creation_time) AS at_utc,
  user_email,
  statement_type,
  (SELECT value FROM UNNEST(labels) WHERE key = 'ns')                AS ns,
  (SELECT value FROM UNNEST(labels) WHERE key = 'adk_agent')         AS adk_agent,
  (SELECT value FROM UNNEST(labels) WHERE key = 'env')               AS env,
  (SELECT value FROM UNNEST(labels) WHERE key = 'tool')              AS tool,
  (SELECT value FROM UNNEST(labels) WHERE key = 'adk-bigquery-tool') AS adk_bigquery_tool,
  ARRAY_TO_STRING(ARRAY(SELECT CONCAT(dataset_id, '.', table_id) FROM UNNEST(referenced_tables)), ',') AS referenced_tables,
  total_bytes_processed AS bytes,
  IF(cache_hit, 'hit', '') AS cache,
  job_id
FROM `region-{region}`.INFORMATION_SCHEMA.{view}
WHERE creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
  AND job_type = 'QUERY'
  AND EXISTS (SELECT 1 FROM UNNEST(labels) WHERE key = 'ns' AND value = @ns)
ORDER BY creation_time DESC
LIMIT @lim
"""


def query_for(scope: str, region: str) -> str:
    """The evidence statement for one scope and region; an unknown scope is refused, not defaulted."""
    if scope not in VIEWS:
        raise ValueError(f"scope must be one of {sorted(VIEWS)}, not {scope!r}")
    return BQ_SQL.format(region=region, view=VIEWS[scope])


def _table(rows: list[dict], columns: list[str]) -> None:
    if not rows:
        print("(no rows — run the probe or a golden prompt first)")
        return
    widths = {c: max(len(c), *(len(str(r.get(c, "") or "")) for r in rows)) for c in columns}
    print("  ".join(c.ljust(widths[c]) for c in columns))
    for r in rows:
        print("  ".join(str(r.get(c, "") or "").ljust(widths[c]) for c in columns))


def bigquery(hours: int, limit: int, scope: str) -> int:
    from google.cloud import bigquery as bq
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    ns = os.environ.get("WORKSHOP_NAMESPACE") or sys.exit("WORKSHOP_NAMESPACE is not set: run `uv run python scripts/namespace.py`")
    region = os.environ.get("BQ_LOCATION", "US").lower()
    client = bq.Client(project=project)
    job = client.query(query_for(scope, region), job_config=bq.QueryJobConfig(
        query_parameters=[bq.ScalarQueryParameter("hours", "INT64", hours), bq.ScalarQueryParameter("lim", "INT64", limit),
                          bq.ScalarQueryParameter("ns", "STRING", ns)],
        labels={"adk_agent": "evidence_script"}))
    rows = [dict(r) for r in job.result()]
    who = "yours" if scope == "user" else "every identity's"
    print(f"== BigQuery jobs labelled ns={ns}, last {hours}h, project {project} (region-{region}), {VIEWS[scope]}: {who}")
    _table(rows, ["at_utc", "user_email", "statement_type", "ns", "adk_agent", "env", "tool", "adk_bigquery_tool", "referenced_tables", "bytes", "cache"])
    hits = sum(1 for r in rows if r.get("cache"))
    if hits:
        print(f"\n{hits} of {len(rows)} rows are query-cache hits: the same user ran the same statement in the last 24 hours and the "
              "table has not changed, so BigQuery answered from the stored result. It scanned nothing (0 bytes, no "
              "referenced_tables) and billed nothing; the first run of each statement carries the tables. The job, its labels "
              "and the statement are recorded either way.")
    return 0



def main() -> int:
    from agents.cymbal_store_ops.preflight import require_sign_in

    require_sign_in()   # an expired sign-in stops here, in words, not as a stack trace later
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hours", type=int, default=1)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--scope", choices=sorted(VIEWS), default="user",
                    help="user: the jobs you submitted (JOBS_BY_USER, roles/bigquery.user); project: everyone's, the "
                         "deployed engines' included (JOBS_BY_PROJECT, needs bigquery.jobs.listAll)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.json:
        print(json.dumps({"backend": "bigquery", "hours": a.hours, "scope": a.scope}))
    return bigquery(a.hours, a.limit, a.scope)


if __name__ == "__main__":
    raise SystemExit(main())
