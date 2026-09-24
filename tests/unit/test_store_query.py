"""Composable reads execute real relational plans; scope never comes from query filters."""
import json
from collections import Counter, defaultdict
from datetime import timedelta
from types import SimpleNamespace

import pytest
from google.adk.tools import FunctionTool
from google.cloud.bigquery.table import Row

from agents.cymbal_store_ops.tools import data_backend
from agents.cymbal_store_ops.tools.backends.bigquery import BigQueryBackend
from agents.cymbal_store_ops.tools.data_backend import NOW, parse_ts
from agents.cymbal_store_ops.tools.store_query import (
    RESOURCES,
    describe_store_data,
    query_store_data,
)
from tests.conftest import FakeToolContext


def ctx(role="store_manager", uid="U-M014", store="S-014"):
    return FakeToolContext({"user:role": role, "user:user_id": uid, "user:store_id": store})


def query(resource, **kwargs):
    return query_store_data(resource, tool_context=ctx(), **kwargs)


@pytest.mark.parametrize("resource", RESOURCES)
def test_each_resource_counts_full_store_source_not_a_backend_page(fake_backend, resource):
    fake_backend.limit = 1
    spec = RESOURCES[resource]
    if resource == "reviews":
        carried = {row["product_id"] for row in fake_backend.inventory if row["store_id"] == "S-014"}
        expected = sum(row["product_id"] in carried for row in fake_backend.reviews)
    else:
        expected = sum(row["store_id"] == "S-014" for row in getattr(fake_backend, spec.fake_attribute))
    result = query(resource, measures=[{"operation": "count"}])
    assert result["status"] == "SUCCESS"
    assert result["rows"] == [{"count_records": expected}]
    assert result["total_matching"] == 1 and not result["has_more"]


def test_inventory_grouping_and_changed_balance_are_computed_from_actual_rows(fake_backend):
    changed = next(row for row in fake_backend.inventory if row["store_id"] == "S-014")
    changed.update(on_hand=137, on_shelf_qty=31, backroom_qty=106)
    expected = defaultdict(lambda: {"count_records": 0, "sum_on_hand": 0, "sum_retail_value_usd": 0})
    for row in fake_backend.inventory:
        if row["store_id"] != "S-014":
            continue
        product = fake_backend._product[row["product_id"]]
        group = expected[product["category"]]
        group["count_records"] += 1
        group["sum_on_hand"] += row["on_hand"]
        group["sum_retail_value_usd"] += row["on_hand"] * product["price_usd"]
    result = query("inventory", group_by=["category"], measures=[{"operation": "count"},
        {"operation": "sum", "field": "on_hand"}, {"operation": "sum", "field": "retail_value_usd"}])
    assert result["total_matching"] == len(expected)
    for row in result["rows"]:
        group = expected[row["category"]]
        assert row["count_records"] == group["count_records"]
        assert row["sum_on_hand"] == group["sum_on_hand"]
        assert row["sum_retail_value_usd"] == pytest.approx(group["sum_retail_value_usd"])
    assert result["query"]["fields"] == ["category"]
    assert "not available-to-promise" in result["data_notes"]


def test_pages_are_stable_complete_and_count_before_pagination(fake_backend):
    expected = sorted(row["product_id"] for row in fake_backend.inventory if row["store_id"] == "S-014")
    seen, offset = [], 0
    while True:
        result = query("inventory", fields=["product_id", "on_hand"], limit=91, offset=offset)
        assert result["total_matching"] == len(expected)
        seen.extend(row["product_id"] for row in result["rows"])
        if not result["has_more"]:
            assert result["next_offset"] is None
            break
        offset = result["next_offset"]
    assert seen == expected
    past = query("inventory", fields=["product_id"], offset=len(expected) + 3)
    assert past["rows"] == [] and past["total_matching"] == len(expected) and not past["has_more"]


def test_filters_compose_and_literal_sql_text_cannot_change_scope(fake_backend):
    expected = sorted(row["product_id"] for row in fake_backend.inventory if row["store_id"] == "S-014"
        and fake_backend._product[row["product_id"]]["category"] == "skincare" and row["on_hand"] > 10)
    actual = query("inventory", fields=["product_id"], filters=[{"field": "category", "value": "SKINCARE"},
        {"field": "on_hand", "operator": "gt", "value": "10"}], limit=100)
    assert actual["total_matching"] == len(expected)
    assert [row["product_id"] for row in actual["rows"]] == expected[:100]
    injection = "x' OR 1=1 --"
    assert query("inventory", filters=[{"field": "product_name", "operator": "contains", "value": injection}])["rows"] == []
    assert query("inventory", filters=[{"field": "product_name", "operator": "contains", "value": "%"}])["rows"] == []


def test_task_ownership_scope_is_enforced_before_user_filters_or_aggregates(fake_backend):
    task = dict(fake_backend.tasks[0], task_id="T-OWN", store_id="S-014", assignee_id="A-1004")
    fake_backend.tasks.append(task)
    own = [row for row in fake_backend.tasks if row["store_id"] == "S-014" and row["assignee_id"] == "A-1004"]
    person = ctx("associate", "A-1004")
    result = query_store_data("tasks", fields=["task_id", "assignee_id"], tool_context=person)
    assert {row["task_id"] for row in result["rows"]} == {row["task_id"] for row in own}
    assert result["scope"] == "own_assigned_tasks"
    other = query_store_data("tasks", filters=[{"field": "assignee_id", "value": "A-1005"}],
        measures=[{"operation": "count"}], tool_context=person)
    assert other["rows"] == [{"count_records": 0}]
    assert query_store_data("loss", tool_context=person)["code"] == "forbidden"
    assert "loss" not in {row["resource"] for row in describe_store_data(tool_context=person)["rows"]}


def test_signin_and_store_boundaries_prevent_queries(fake_backend):
    assert query_store_data("inventory")["status"] == "ERROR"
    assert describe_store_data()["status"] == "ERROR"
    assert query_store_data("inventory", store_id="S-002", tool_context=ctx())["code"] == "forbidden"
    assert query_store_data("loss", tool_context=ctx("associate", "A-1004"))["code"] == "forbidden"
    assert fake_backend.calls == []
    actual = query_store_data("inventory", store_id="S-002", measures=[{"operation": "count"}], tool_context=ctx("district_manager"))
    assert actual["rows"] == [{"count_records": sum(row["store_id"] == "S-002" for row in fake_backend.inventory)}]
    empty = query_store_data("inventory", store_id="S-002' OR TRUE --", tool_context=ctx("district_manager"))
    assert empty["rows"] == []


@pytest.mark.parametrize("options", [
    {"fields": ["store_id"]}, {"fields": ["product_id` FROM products --"]},
    {"filters": [{"field": "on_hand", "operator": "OR TRUE", "value": "0"}]},
    {"filters": [{"field": "on_hand", "value": "1", "sql": "OR 1=1"}]},
    {"measures": [{"operation": "sum", "field": "product_name"}]},
    {"measures": [{"operation": "sum"}]},
    {"order_by": [{"field": "on_hand; DROP TABLE products"}]},
    {"order_by": [{"field": "on_hand", "direction": "desc; DROP TABLE products"}]},
    {"group_by": ["category"], "fields": ["product_name"]},
    {"filters": [{"field": "on_hand", "operator": "contains", "value": "1"}]},
    {"filters": [{"field": "price_usd", "value": "NaN"}]},
    {"filters": [{"field": "bopis_eligible", "value": "1"}]},
    {"limit": 0}, {"limit": True}, {"offset": 0.5}, {"offset": -1},
])
def test_invalid_queries_and_identifiers_never_reach_sql(fake_backend, options):
    result = query("inventory", **options)
    assert result["status"] == "ERROR" and result["code"] == "invalid_query"
    assert fake_backend.calls == []


def test_empty_matches_and_group_only_metadata_are_precise(fake_backend):
    none = [{"field": "product_id", "value": "no-such-product"}]
    assert query("inventory", filters=none)["total_matching"] == 0
    aggregate = query("inventory", filters=none, measures=[{"operation": "count"}, {"operation": "sum", "field": "on_hand"}])
    assert aggregate["rows"] == [{"count_records": 0, "sum_on_hand": None}]
    groups = query("inventory", group_by=["category"])
    assert groups["query"]["fields"] == ["category"]
    assert {row["category"] for row in groups["rows"]} == {p["category"] for p in fake_backend.products}


def test_forecast_dates_and_typed_filters_do_not_claim_future_actuals(fake_backend):
    sample = next(row for row in fake_backend.traffic if row["store_id"] == "S-014")
    fake_backend.traffic.append({**sample, "ts_hour": (NOW + timedelta(days=1)).isoformat()})
    result = query("traffic", group_by=["day", "is_forecast"], measures=[{"operation": "sum", "field": "sales_usd"}])
    assert result["status"] == "SUCCESS"
    dates = {row["day"]: row for row in result["rows"]}
    assert dates[(NOW.date() - timedelta(days=1)).isoformat()]["is_forecast"] is False
    assert dates[NOW.date().isoformat()]["is_forecast"] is True
    assert dates[(NOW.date() + timedelta(days=1)).isoformat()]["is_forecast"] is True
    yesterday = (NOW.date() - timedelta(days=1)).isoformat()
    expected = sum(row["sales_usd"] for row in fake_backend.traffic if row["store_id"] == "S-014"
                   and parse_ts(row["ts_hour"]).astimezone(NOW.tzinfo).date().isoformat() == yesterday)
    actual = query("traffic", filters=[{"field": "day", "value": yesterday}, {"field": "is_forecast", "value": "false"}],
                   measures=[{"operation": "sum", "field": "sales_usd"}])
    assert actual["rows"][0]["sum_sales_usd"] == pytest.approx(expected)
    assert "No SKU sales" in actual["data_notes"]


def test_report_delivers_full_scoped_inventory_without_model_row_dump(fake_backend):
    context = ctx()
    expected = sorted(row["product_id"] for row in fake_backend.inventory if row["store_id"] == "S-014")
    result = query_store_data("inventory", fields=["product_id", "on_hand"], delivery="report",
                              limit=1, offset=100, tool_context=context)
    report = context.state["ui:report"]
    assert result["status"] == "SUCCESS" and result["rows"] == []
    assert result["report_id"] == report["id"] and result["display"] == "report"
    assert result["complete"] is report["complete"] is True
    assert result["row_count"] == result["total_matching"] == len(expected)
    assert [row["product_id"] for row in report["rows"]] == expected
    assert report["columns"] == ["product_id", "on_hand"] and report["store_id"] == "S-014"
    assert len(json.dumps(result)) < 1500
    assert "ui:report" not in ctx().state


def test_report_cap_is_explicit_and_does_not_misrepresent_completeness(fake_backend):
    template = next(row for row in fake_backend.tasks if row["store_id"] == "S-014")
    fake_backend.tasks = [{**template, "task_id": f"T-CAP-{i:05}"} for i in range(5003)]
    context = ctx()
    result = query_store_data("tasks", fields=["task_id"], delivery="report", tool_context=context)
    report = context.state["ui:report"]
    assert result["status"] == "SUCCESS"
    assert result["row_count"] == len(report["rows"]) == 5000
    assert result["total_matching"] == report["total_matching"] == 5003
    assert result["complete"] is report["complete"] is False


def test_report_preserves_associate_scope_and_empty_aggregate_columns(fake_backend):
    context = ctx("associate", "A-1004")
    expected = sorted(row["task_id"] for row in fake_backend.tasks
                      if row["store_id"] == "S-014" and row["assignee_id"] == "A-1004")
    result = query_store_data("tasks", fields=["task_id"], delivery="report", tool_context=context)
    assert result["status"] == "SUCCESS"
    assert [row["task_id"] for row in context.state["ui:report"]["rows"]] == expected
    previous = context.state["ui:report"]
    assert query_store_data("loss", delivery="report", tool_context=context)["status"] == "ERROR"
    assert context.state["ui:report"] == previous
    empty = ctx()
    result = query_store_data("inventory", delivery="report", group_by=["category"],
        filters=[{"field": "product_id", "value": "missing"}], measures=[{"operation": "sum", "field": "on_hand"}],
        tool_context=empty)
    assert result["complete"] is True and result["row_count"] == 0
    assert empty.state["ui:report"]["columns"] == ["category", "sum_on_hand"]


@pytest.mark.asyncio
async def test_adk_nested_input_schema_and_actual_functiontool_execution(fake_backend):
    tool = FunctionTool(query_store_data)
    schema = tool._get_declaration().model_dump(mode="json", exclude_none=True)["parameters_json_schema"]
    assert {"filters", "measures", "group_by", "order_by"} <= schema["properties"].keys()
    result = await tool.run_async(args={"resource": "loss", "group_by": ["event_type"],
        "measures": [{"operation": "count"}, {"operation": "sum", "field": "qty"}],
        "filters": [{"field": "product_id", "value": "P-0420"}], "order_by": [{"field": "event_type", "direction": "asc"}]},
        tool_context=ctx())
    rows = [row for row in fake_backend.shrink if row["store_id"] == "S-014" and row["product_id"] == "P-0420"]
    counts = Counter(row["event_type"] for row in rows)
    units = Counter()
    for row in rows:
        units[row["event_type"]] += row["qty"]
    assert result["rows"] == [{"event_type": kind, "count_records": counts[kind], "sum_qty": units[kind]} for kind in sorted(counts)]


def test_bigquery_compiles_parameters_and_serializes_nested_rows_without_stringifying(monkeypatch):
    captured = []
    expected = [{"task_id": "T-OWN", "note": 'Includes {quoted braces} and "quotes"', "due_at": "2026-10-03T14:30:00Z"}]

    class Job:
        def result(self, **kwargs):
            return [Row((json.dumps(expected), 17), {"page_rows_json": 0, "total_matching": 1})]

    class Client:
        def query_and_wait(self, sql, **kwargs):
            captured.append((sql, kwargs))
            return Job().result()

    backend = BigQueryBackend.__new__(BigQueryBackend)
    backend.client, backend.main, backend.labels = Client(), "test_project.test_dataset", {}
    backend.cfg = SimpleNamespace(data=SimpleNamespace(maximum_bytes_billed=1000000, statement_timeout_s=10))
    monkeypatch.setattr(data_backend, "make_backend", lambda: backend)
    injection = "x' OR 1=1 --"
    result = query_store_data("tasks", fields=["task_id", "note", "due_at"], filters=[{"field": "note", "operator": "contains", "value": injection}],
                             tool_context=ctx("associate", "A-1004"))
    assert result["total_matching"] == 17 and len(result["rows"]) == 1
    assert result["rows"][0]["task_id"] == expected[0]["task_id"]
    assert result["rows"][0]["note"] == expected[0]["note"]
    assert parse_ts(result["rows"][0]["due_at"]) == parse_ts(expected[0]["due_at"])
    sql, kwargs = captured[0]
    assert "TO_JSON_STRING(ARRAY(SELECT AS STRUCT * FROM page)) AS page_rows_json" in sql
    assert "assignee_id = @scope_user" in sql and "store_id = @scope_store" in sql
    assert injection not in sql and "A-1004" not in sql and "S-014" not in sql
    parameters = {p.name: p.value for p in kwargs["job_config"].query_parameters}
    assert parameters["value_0"] == injection and parameters["scope_user"] == "A-1004" and parameters["scope_store"] == "S-014"
    assert kwargs["job_config"].maximum_bytes_billed == 1000000
    assert "COUNT(*) FROM result" in sql and "LIMIT @page_limit OFFSET @page_offset" in sql


@pytest.mark.parametrize("resource,field", [
    ("orders", "status"), ("tasks", "status"), ("tasks", "task_type"), ("tasks", "source"),
    ("loss", "event_type"), ("feedback", "topic"), ("deliveries", "status"), ("roster", "role"),
    ("inventory", "category"),
])
def test_closed_domains_are_discoverable_and_invalid_exact_filters_do_not_query(fake_backend, resource, field):
    from pathlib import Path
    spec = RESOURCES[resource]
    discovery = describe_store_data(resource, tool_context=ctx())
    allowed = discovery["rows"][0]["allowed_values"][field]
    table = "products" if field == "category" else spec.table
    schema = json.loads((Path(__file__).resolve().parents[2] / "data" / "schemas" / f"{table}.json").read_text())
    declared = next(row["description"].split("|") for row in schema if row["name"] == field)
    assert set(allowed) == set(declared)
    for operator in ["eq", "ne"]:
        result = query(resource, filters=[{"field": field, "operator": operator, "value": "unsupported-state"}])
        assert result["status"] == "ERROR" and result["code"] == "invalid_query"
        assert all(value in result["error_details"] for value in allowed)
    assert fake_backend.calls == []
    actual = query(resource, fields=[field], filters=[{"field": field, "value": allowed[0].upper()}])
    assert actual["status"] == "SUCCESS"
    assert all(row[field] == allowed[0] for row in actual["rows"])


def test_valid_absent_order_status_is_distinct_from_unsupported_status(fake_backend):
    fake_backend.orders = [row for row in fake_backend.orders if row["status"] != "collected"]
    absent = query("orders", filters=[{"field": "status", "value": "collected"}])
    assert absent["status"] == "SUCCESS" and absent["total_matching"] == 0
    invalid = query("orders", filters=[{"field": "status", "value": "completed"}])
    assert invalid["status"] == "ERROR"
    partial = query("orders", filters=[{"field": "status", "operator": "contains", "value": "pick"}])
    assert partial["status"] == "SUCCESS"
    assert all(row["status"] == "picked" for row in partial["rows"])


def test_compound_catalog_inventory_query_uses_actual_changed_attributes(fake_backend):
    changed = fake_backend._product["P-0101"]
    changed.update(is_fragrance_free=True, skin_types="dry,sensitive", key_ingredients="ceramides,glycerin",
                   rating_avg=4.9, rating_count=123, price_usd=19.0)
    filters = [{"field": "is_fragrance_free", "value": "true"},
        {"field": "skin_types", "operator": "contains", "value": "sensitive"},
        {"field": "key_ingredients", "operator": "contains", "value": "ceramides"},
        {"field": "price_usd", "operator": "lt", "value": "25"},
        {"field": "rating_avg", "operator": "gte", "value": "4.5"},
        {"field": "on_hand", "operator": "gt", "value": "0"}]
    fields = ["product_id", "is_fragrance_free", "skin_types", "key_ingredients", "price_usd", "rating_avg", "rating_count", "on_hand"]
    expected = []
    for row in fake_backend.inventory:
        p = fake_backend._product[row["product_id"]]
        if (row["store_id"] == "S-014" and p["is_fragrance_free"] and "sensitive" in (p["skin_types"] or "")
            and "ceramides" in (p["key_ingredients"] or "") and p["price_usd"] < 25
            and (p["rating_avg"] or 0) >= 4.5 and row["on_hand"] > 0):
            expected.append({key: row["on_hand"] if key == "on_hand" else p[key] for key in fields})
    expected.sort(key=lambda row: row["product_id"])
    result = query("inventory", fields=fields, filters=filters, order_by=[{"field": "product_id"}], limit=100)
    assert result["rows"] == expected and any(row["product_id"] == "P-0101" for row in expected)
    context = ctx()
    report = query_store_data("inventory", fields=fields, filters=filters, delivery="report",
                              order_by=[{"field": "product_id"}], tool_context=context)
    assert report["rows"] == [] and context.state["ui:report"]["rows"] == expected
    assert report["complete"] is True


def test_nullable_catalog_fields_and_bigquery_join_expressions(fake_backend):
    from agents.cymbal_store_ops.tools.store_query import _bq_source
    p = fake_backend._product["P-0101"]
    p.update(skin_types=None, key_ingredients=None, rating_avg=None, rating_count=None)
    result = query("inventory", fields=["product_id", "skin_types", "key_ingredients", "rating_avg", "rating_count"],
                   filters=[{"field": "product_id", "value": p["product_id"]}])
    assert result["rows"] == [{"product_id": p["product_id"], "skin_types": None,
        "key_ingredients": None, "rating_avg": None, "rating_count": None}]
    backend = SimpleNamespace(_t=lambda table: f"`project.dataset.{table}`")
    sql = _bq_source(backend, RESOURCES["inventory"])
    for field in ["is_fragrance_free", "skin_types", "key_ingredients", "rating_avg", "rating_count"]:
        assert f"p.{field} AS `{field}`" in sql
    discovery = describe_store_data("inventory", tool_context=ctx())
    assert set(discovery["delivery_modes"]) == {"answer", "report"}


def test_reviews_scope_uses_product_membership_including_zero_stock_without_duplicates(fake_backend):
    own_pid, other_pid = 'P-0101', 'P-0420'
    template = fake_backend.inventory[0]
    fake_backend.inventory = [dict(template, store_id='S-014', product_id=own_pid, on_hand=0),
                              dict(template, store_id='S-014', product_id=own_pid, on_hand=0),
                              dict(template, store_id='S-002', product_id=other_pid, on_hand=9)]
    expected = sorted(row['review_id'] for row in fake_backend.reviews if row['product_id'] == own_pid)
    for role, user in [('associate', 'A-1004'), ('store_manager', 'U-M014')]:
        result = query_store_data('reviews', fields=['review_id', 'product_id'], limit=100,
                                  tool_context=ctx(role, user))
        assert result['status'] == 'SUCCESS'
        assert sorted(row['review_id'] for row in result['rows']) == expected
        assert result['total_matching'] == len(expected)
        assert query_store_data('reviews', store_id='S-002', tool_context=ctx(role, user))['code'] == 'forbidden'
    other = query_store_data('reviews', fields=['product_id'], store_id='S-002',
                             tool_context=ctx('district_manager'))
    assert other['rows'] and all(row['product_id'] == other_pid for row in other['rows'])
    assert query_store_data('reviews')['status'] == 'ERROR'
    absent = query_store_data('reviews', store_id='S-999', tool_context=ctx('district_manager'))
    assert absent['total_matching'] == 0


def test_review_filter_aggregate_and_report_share_complete_matching_set(fake_backend):
    pid = 'P-0101'
    fake_backend.reviews = [dict(review_id=f'R-NEW-{i:03}', product_id=pid, rating=rating,
                                title='Experience', body=body, skin_type=skin,
                                created_at=f'2026-09-{day:02}T10:00:00-05:00')
                           for i, (rating, body, skin, day) in enumerate([
                               (2, 'Texture felt heavy', 'sensitive', 12),
                               (1, 'Heavy texture', 'sensitive', 15),
                               (3, 'Texture fine', 'sensitive', 16),
                               (2, 'Texture changed', 'dry', 19),
                               (2, 'Texture issue', 'sensitive', 1)])]
    filters = [{'field': 'product_id', 'value': pid}, {'field': 'skin_type', 'value': 'sensitive'},
               {'field': 'rating', 'operator': 'lte', 'value': '2'},
               {'field': 'body', 'operator': 'contains', 'value': 'TEXTURE'},
               {'field': 'created_at', 'operator': 'gte', 'value': '2026-09-10T00:00:00-05:00'}]
    result = query('reviews', filters=filters, group_by=['skin_type'],
                   measures=[{'operation': 'count'}, {'operation': 'avg', 'field': 'rating'}])
    assert result['rows'] == [{'skin_type': 'sensitive', 'count_records': 2, 'avg_rating': 1.5}]
    context = ctx('associate', 'A-1004')
    report = query_store_data('reviews', fields=['review_id', 'rating', 'body', 'created_at'], filters=filters,
                              order_by=[{'field': 'rating'}], delivery='report', tool_context=context)
    assert report['rows'] == [] and report['row_count'] == report['total_matching'] == 2
    assert report['complete'] is True
    assert [row['review_id'] for row in context.state['ui:report']['rows']] == ['R-NEW-001', 'R-NEW-000']
    assert 'not this store' in report['data_notes']
    page = query('reviews', filters=filters, fields=['review_id'], limit=1)
    assert page['total_matching'] == 2 and page['has_more']
    discovery = describe_store_data('reviews', tool_context=context)['rows'][0]
    assert {'skin_type', 'skin_types', 'rating', 'rating_avg', 'rating_count'} <= discovery['fields'].keys()


def test_bigquery_reviews_scope_is_membership_exists_not_invented_review_store(monkeypatch):
    captured = []
    class Job:
        def result(self, **kwargs):
            return [Row(('[]', 0), {'page_rows_json': 0, 'total_matching': 1})]
    class Client:
        def query_and_wait(self, sql, **kwargs):
            captured.append((sql, kwargs))
            return Job().result()
    backend = BigQueryBackend.__new__(BigQueryBackend)
    backend.client, backend.main, backend.labels = Client(), 'test_project.test_dataset', {}
    backend.cfg = SimpleNamespace(data=SimpleNamespace(maximum_bytes_billed=1000000, statement_timeout_s=10))
    monkeypatch.setattr(data_backend, 'make_backend', lambda: backend)
    result = query_store_data('reviews', filters=[{'field': 'skin_type', 'value': 'sensitive'}], tool_context=ctx())
    assert result['status'] == 'SUCCESS'
    sql, options = captured[0]
    assert 'r.store_id' not in sql
    assert '@scope_store AS store_id' in sql
    assert 'EXISTS (SELECT 1 FROM `test_project.test_dataset.store_inventory` membership' in sql
    assert 'membership.store_id = @scope_store AND membership.product_id = r.product_id' in sql
    assert 'on_hand >' not in sql
    assert 'r.skin_type AS `skin_type`' in sql and 'p.skin_types AS `skin_types`' in sql
    parameters = {p.name: p.value for p in options['job_config'].query_parameters}
    assert parameters['scope_store'] == 'S-014' and parameters['value_0'] == 'sensitive'
