"""Quickstart 05 — data analyst agent.

The ADK BigQuery toolset with its analytics tools: schema discovery, read-only SQL, `ask_data_insights`
(Conversational Analytics), `forecast` and `detect_anomalies`. Governance is configuration plus one callback:
WriteMode.BLOCKED, row and byte caps, job labels, and `block_people_data`, which refuses any tool call that names
the associates or coaching_signals tables (people data goes through the store manager's role-gated tools, never
raw SQL). Point it at another dataset by changing the environment config, not the code.
"""
from __future__ import annotations

import json
import re
import warnings

warnings.filterwarnings("ignore", message=r".*\[EXPERIMENTAL\].*", module=r"google\.adk.*")

import google.auth  # noqa: E402
from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.apps import App  # noqa: E402
from google.adk.integrations.bigquery import (  # noqa: E402
    BigQueryCredentialsConfig,
    BigQueryToolset,
)
from google.adk.integrations.bigquery.config import BigQueryToolConfig, WriteMode  # noqa: E402
from google.adk.tools import BaseTool, ToolContext  # noqa: E402

from agents.cymbal_store_ops.callbacks import enforce_dataset_allowlist_before_tool  # noqa: E402
from agents.cymbal_store_ops.config import load_env_config  # noqa: E402
from agents.cymbal_store_ops.models import workshop_model  # noqa: E402

TOOLS = ["list_table_ids", "get_table_info", "execute_sql", "ask_data_insights", "forecast", "detect_anomalies"]
INSTRUCTION = """You are the store operations data analyst for Cymbal Beauty district and store managers. The data
lives in the BigQuery dataset `{project}.{dataset}`: stores, products, store_inventory (on_hand, on_shelf_qty,
backroom_qty, reorder_point), bopis_orders, store_traffic (one row per store and open hour: store_id, ts_hour in
UTC, visitors, transactions, sales_usd; stores keep America/Chicago time, so a daily series sums visitors by
DATE(ts_hour, 'America/Chicago')), shrink_events, store_tasks, replenishment, guest_feedback, reviews. People data (associates, coaching signals) is not available here: say so and point to the
store manager's assistant, where coaching signals need a manager role.
- Discover columns with get_table_info before writing SQL for a table you have not used yet.
- Answer with numbers from execute_sql; use forecast for "next weeks" questions on a time series (store_traffic),
  detect_anomalies for "anything unusual" questions, and ask_data_insights only for open-ended exploration.
- Answer in one or two sentences with the numbers, then one line starting "SQL:" with the query you ran;
  when you ran no query, give no SQL line.
- Read-only: never attempt INSERT, UPDATE, DELETE or DDL. Never name an associate in a shrink answer."""


PEOPLE_TABLES = re.compile(r"\b(associates|coaching_signals)\b", re.IGNORECASE)


def block_people_data(tool: BaseTool, args: dict, tool_context: ToolContext) -> dict | None:
    """Refuse a query, schema lookup, forecast or data question that names a people table, whatever its arguments."""
    if PEOPLE_TABLES.search(json.dumps(args, default=str)):
        return {"status": "ERROR", "error_details": "blocked by policy: people data (associates, coaching signals) is "
                "not available to the analyst; coaching signals are for managers in the store manager's assistant"}
    return None


def make_root_agent() -> LlmAgent:
    cfg = load_env_config()
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    toolset = BigQueryToolset(
        tool_filter=TOOLS,
        credentials_config=BigQueryCredentialsConfig(credentials=credentials),
        bigquery_tool_config=BigQueryToolConfig(
            write_mode=WriteMode.BLOCKED, max_query_result_rows=cfg.data.max_query_result_rows,
            maximum_bytes_billed=cfg.data.maximum_bytes_billed, compute_project_id=cfg.project,
            location=cfg.bigquery.location, application_name="data_analyst_agent",
            job_labels={**cfg.bigquery.job_labels, "adk_agent": "data_analyst_agent"}),
    )
    return LlmAgent(
        name="data_analyst_agent",
        model=workshop_model(cfg),
        description="Answers store operations questions over the Cymbal Beauty dataset with read-only BigQuery tools.",
        instruction=INSTRUCTION.format(project=cfg.project, dataset=cfg.bigquery.dataset),
        tools=[toolset],
        before_tool_callback=[block_people_data, enforce_dataset_allowlist_before_tool],   # people data, then SELECT-only in this dataset
    )


def create_app() -> App:
    return App(name="data_analyst_agent", root_agent=make_root_agent())


app = create_app()
root_agent = app.root_agent
