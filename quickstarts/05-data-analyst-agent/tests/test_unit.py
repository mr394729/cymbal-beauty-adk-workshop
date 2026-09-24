"""Configuration is the governance: blocked writes, caps and labels. No BigQuery calls."""
from __future__ import annotations

from google.adk.integrations.bigquery.config import WriteMode


def test_toolset_is_read_only_and_capped(quickstart, monkeypatch):
    import google.auth
    from google.auth.credentials import AnonymousCredentials

    monkeypatch.setattr(google.auth, "default", lambda scopes=None: (AnonymousCredentials(), "unit-test-project"))
    agent = quickstart.make_root_agent()
    (toolset,) = agent.tools
    cfg = toolset._tool_settings
    assert cfg.write_mode == WriteMode.BLOCKED and cfg.max_query_result_rows == 50
    assert cfg.job_labels["adk_agent"] == "data_analyst_agent"
    assert "forecast" in toolset.tool_filter and "detect_anomalies" in toolset.tool_filter


def test_people_tables_are_refused_in_every_tool(quickstart):
    """associates and coaching_signals never reach BigQuery through the analyst, in SQL or in any other argument."""
    sql = {"project_id": "p", "query": "SELECT * FROM `p.cymbal_beauty_unit_dev.coaching_signals`"}
    assert quickstart.block_people_data(None, sql, None)["status"] == "ERROR"
    info = {"project_id": "p", "dataset_id": "cymbal_beauty_unit_dev", "table_id": "Associates"}
    assert quickstart.block_people_data(None, info, None)["status"] == "ERROR"
    ok = {"project_id": "p", "query": "SELECT store_id, SUM(visitors) FROM `p.cymbal_beauty_unit_dev.store_traffic` GROUP BY 1"}
    assert quickstart.block_people_data(None, ok, None) is None


def test_analyst_owns_the_people_data_callback(quickstart, monkeypatch):
    import google.auth
    from google.auth.credentials import AnonymousCredentials

    monkeypatch.setattr(google.auth, "default", lambda scopes=None: (AnonymousCredentials(), "unit-test-project"))
    from agents.cymbal_store_ops.callbacks import enforce_dataset_allowlist_before_tool

    assert quickstart.make_root_agent().before_tool_callback == [quickstart.block_people_data, enforce_dataset_allowlist_before_tool]
