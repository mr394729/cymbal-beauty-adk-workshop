"""Whole-store summaries and bounded inventory reads retain scope and complete counts."""
from unittest.mock import Mock

import pytest

from agents.cymbal_store_ops.tools.backends.bigquery import BigQueryBackend
from agents.cymbal_store_ops.tools.inventory_summary import (
    get_store_inventory_summary,
    list_store_inventory,
)
from tests.conftest import FakeToolContext


def ctx(role="store_manager", store="S-014"):
    return FakeToolContext({"user:role": role, "user:user_id": "U-M014", "user:store_id": store})


def test_store_summary_counts_every_sku_not_only_previous_product(fake_backend):
    stocks = [r for r in fake_backend.inventory if r["store_id"] == "S-014"]
    result = get_store_inventory_summary(tool_context=ctx())
    assert result["status"] == "SUCCESS"
    totals = result["totals"]
    assert totals["sku_count"] == result["inventory_row_count"] == len(stocks) == 600
    assert totals["stocked_sku_count"] == sum(r["on_hand"] > 0 for r in stocks)
    assert totals["on_hand_units"] == sum(r["on_hand"] for r in stocks)
    assert totals["on_hand_units"] == totals["on_shelf_units"] + totals["backroom_units"]
    assert totals["empty_shelf_sku_count"] == sum(r["on_shelf_qty"] == 0 and r["on_hand"] > 0 for r in stocks)
    assert totals["out_of_stock_sku_count"] == sum(r["on_hand"] == 0 for r in stocks)
    assert totals["low_stock_sku_count"] == sum(r["on_hand"] < r["reorder_point"] for r in stocks)
    assert sum(r["sku_count"] for r in result["rows"]) == 600
    assert result["category_count"] == len(result["rows"]) < 20
    assert not result["reservation_data_included"] and not result["available_to_promise_known"]


def test_category_summary_and_unknown_category_are_unambiguous(fake_backend):
    all_rows = get_store_inventory_summary(tool_context=ctx())["rows"]
    skincare = get_store_inventory_summary(" Skincare ", ctx())
    expected = next(r for r in all_rows if r["category"] == "skincare")
    assert skincare["rows"] == [expected]
    assert skincare["totals"]["sku_count"] == expected["sku_count"] < 600
    assert skincare["store_inventory_row_count"] == 600
    unknown = get_store_inventory_summary("spaceships", ctx())
    assert unknown["status"] == "ERROR" and unknown["code"] == "invalid_argument"
    assert "skincare" in unknown["available_categories"]


def test_inventory_paging_covers_complete_store_without_duplicates(fake_backend):
    seen = []
    offset = 0
    while True:
        page = list_store_inventory(limit=75, offset=offset, tool_context=ctx())
        assert page["total_matching"] == 600
        assert 0 < len(page["rows"]) <= 75
        seen.extend(r["product_id"] for r in page["rows"])
        if not page["has_more"]:
            assert page["next_offset"] is None
            break
        offset = page["next_offset"]
    assert seen == sorted(set(seen)) and len(seen) == 600
    past = list_store_inventory(offset=700, tool_context=ctx())
    assert past["rows"] == [] and past["total_matching"] == 600 and not past["has_more"]


def test_exact_product_and_availability_filters_use_current_balances(fake_backend):
    hero = list_store_inventory(query_text="P-0101", tool_context=ctx())
    assert hero["total_matching"] == 1
    assert hero["rows"][0]["on_hand"] == 7
    assert list_store_inventory(query_text="P-0101", availability="empty_shelf", tool_context=ctx())["total_matching"] == 1
    assert list_store_inventory(query_text="P-0101", availability="out_of_stock", tool_context=ctx())["total_matching"] == 0
    assert list_store_inventory(query_text="Lumiere Hydra", tool_context=ctx())["total_matching"] == 1
    stock = next(r for r in fake_backend.inventory if r["store_id"] == "S-014" and r["product_id"] == "P-0101")
    stock.update(on_hand=0, on_shelf_qty=0, backroom_qty=0)
    assert list_store_inventory(query_text="P-0101", availability="out_of_stock", tool_context=ctx())["total_matching"] == 1
    assert list_store_inventory(query_text="P-0101", availability="empty_shelf", tool_context=ctx())["total_matching"] == 0
    assert list_store_inventory(query_text="P-0101", availability="low_stock", tool_context=ctx())["total_matching"] == 1


@pytest.mark.parametrize("options", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"availability": "reserved"}])
def test_invalid_page_never_reads_backend(fake_backend, options):
    assert list_store_inventory(**options, tool_context=ctx())["code"] == "invalid_argument"
    assert not fake_backend.calls


def test_scope_and_unknown_store_do_not_leak_inventory(fake_backend):
    assert get_store_inventory_summary()["status"] == "ERROR"
    assert list_store_inventory(store_id="S-002", tool_context=ctx("associate"))["code"] == "forbidden"
    assert not fake_backend.calls
    other = list_store_inventory(store_id="S-002", tool_context=ctx("district_manager"))
    assert other["status"] == "SUCCESS" and other["store_id"] == "S-002" and other["total_matching"] == 600
    assert get_store_inventory_summary(tool_context=ctx(store="S-NONE"))["code"] == "not_found"
    assert list_store_inventory(category="not-a-category", tool_context=ctx())["code"] == "invalid_argument"


def bq_stub(rows):
    backend = BigQueryBackend.__new__(BigQueryBackend)
    backend.main = "test_project.test_dataset"
    backend._query = Mock(return_value=rows)
    return backend


def test_bigquery_summary_aggregates_before_return_and_matches_fake(fake_backend):
    expected = fake_backend.get_store_inventory_summary(store_id="S-014")
    backend = bq_stub(expected["rows"])
    assert backend.get_store_inventory_summary(store_id="S-014") == expected
    sql, params = backend._query.call_args.args
    assert "GROUP BY p.category" in sql and "WHERE i.store_id = @sid" in sql
    assert "COUNT(DISTINCT i.product_id)" in sql and "SUM(i.on_hand)" in sql
    assert params == {"sid": "S-014"} and backend._query.call_count == 1


def test_bigquery_page_retains_total_on_empty_page_and_binds_search(fake_backend):
    category = "skincare"
    backend = bq_stub([{"page_rows": [], "total_matching": 123, "available_categories": [category]}])
    query = "' OR 1=1 --"
    result = backend.list_store_inventory(store_id="S-014", category=category, query_text=query, offset=200)
    assert result["total_matching"] == 123 and result["rows"] == [] and not result["has_more"]
    sql, params = backend._query.call_args.args
    assert query not in sql and params["query"] == query.casefold()
    assert params["sid"] == "S-014" and params["offset"] == 200
    assert "ORDER BY product_id LIMIT @lim OFFSET @offset" in sql
    assert "SELECT COUNT(*) FROM matching" in sql and backend._query.call_count == 1


def test_bigquery_failures_remain_errors():
    backend = bq_stub([])
    backend._query.side_effect = RuntimeError("source unavailable")
    assert backend.get_store_inventory_summary(store_id="S-014")["status"] == "ERROR"
    assert backend.list_store_inventory(store_id="S-014")["status"] == "ERROR"
