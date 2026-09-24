"""Exercise the real SDK query RPC while replacing only the HTTP boundary."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from google.api_core.exceptions import BadRequest
from google.auth.credentials import AnonymousCredentials
from google.cloud import bigquery

from agents.cymbal_store_ops.config import DataLimits
from agents.cymbal_store_ops.tools.backends.bigquery import BigQueryBackend


def backend(response):
    b = BigQueryBackend.__new__(BigQueryBackend)
    b.cfg = SimpleNamespace(data=DataLimits())
    b.labels = {"ns": "transport_test", "env": "dev", "data_backend": "bigquery"}
    b.main = "test-project.test_dataset"
    b.client = bigquery.Client(project="test-project", location="US", credentials=AnonymousCredentials())
    b.client._connection.api_request = Mock(return_value=response)
    return b


def response(rows):
    return {"jobComplete": True, "totalRows": str(len(rows)),
            "jobReference": {"projectId": "test-project", "jobId": "read-job", "location": "US"},
            "schema": {"fields": [{"name": "units", "type": "INTEGER"},
                                   {"name": "observed", "type": "DATE"}]},
            "rows": [{"f": [{"v": str(n)}, {"v": "2026-10-03"}]} for n in rows]}


def test_read_query_uses_one_rpc_with_same_parameters_labels_cost_cap_and_limit():
    b = backend(response([7, 3]))
    values = b._query("SELECT units, observed WHERE store_id=@sid LIMIT @lim",
                      {"sid": "S-014", "lim": 2}, tool="read_stock", limit=2)
    assert values == [{"units": 7, "observed": "2026-10-03"},
                      {"units": 3, "observed": "2026-10-03"}]
    call = b.client._connection.api_request
    assert call.call_count == 1
    sent = call.call_args.kwargs
    assert sent["method"] == "POST" and sent["path"] == "/projects/test-project/queries"
    request = sent["data"]
    assert request["location"] == "US" and request["maxResults"] == 2
    assert request["maximumBytesBilled"] == str(b.cfg.data.maximum_bytes_billed)
    assert request["labels"] == {**b.labels, "tool": "read_stock"}
    assert request["queryParameters"] == [
        {"name": "sid", "parameterType": {"type": "STRING"}, "parameterValue": {"value": "S-014"}},
        {"name": "lim", "parameterType": {"type": "INT64"}, "parameterValue": {"value": "2"}},
    ]
    assert sent["timeout"] == b.cfg.data.statement_timeout_s
    assert 0 < request["timeoutMs"] <= b.cfg.data.statement_timeout_s * 1000
    assert request.get("jobCreationMode") != "JOB_CREATION_OPTIONAL"
    assert request.get("useQueryCache") is not False  # benchmark-only override did not ship


def test_read_retains_empty_result_and_surfaces_query_failure_without_fallback():
    b = backend(response([]))
    assert b._query("SELECT 1 WHERE FALSE", tool="empty") == []
    failure = BadRequest("source unavailable")
    b.client._connection.api_request.side_effect = failure
    b.client.query = Mock(side_effect=AssertionError("No insert retry for a rejected read"))
    with pytest.raises(BadRequest, match="source unavailable"):
        b._query("SELECT missing_column", tool="broken")
    assert b.client.query.call_count == 0


def test_query_wait_receives_configured_budget_and_dml_keeps_explicit_job():
    b = backend(response([]))
    b.client.query_and_wait = Mock(return_value=[])
    b._query("SELECT 1", tool="bounded", limit=1)
    options = b.client.query_and_wait.call_args.kwargs
    assert options["api_timeout"] == options["wait_timeout"] == b.cfg.data.statement_timeout_s
    assert options["max_results"] == 1
    b.client.query_and_wait.reset_mock()
    job = SimpleNamespace(num_dml_affected_rows=1, result=Mock())
    b.client.query = Mock(return_value=job)
    assert b._dml("UPDATE store_tasks SET status=@status", {"status": "complete"}, tool="complete") == 1
    assert b.client.query_and_wait.call_count == 0
    assert b.client.query.call_args.kwargs["timeout"] == b.cfg.data.statement_timeout_s
    job.result.assert_called_once_with(timeout=b.cfg.data.statement_timeout_s)
