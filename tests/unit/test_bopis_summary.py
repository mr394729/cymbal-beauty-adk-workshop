"""Product pickup windows must survive aggregation without becoming the store-wide window."""
from datetime import datetime

from agents.cymbal_store_ops.tools.domain_tools import _summarise_bopis


def test_counts_and_promise_windows_are_scoped_to_each_product():
    result = {"pending_count": 4, "rows": [
        {"product_id": "P-1", "qty": 2, "promised_at": "2026-10-03T15:00:00Z"},
        {"product_id": "P-1", "qty": 1, "promised_at": "2026-10-03T09:30:00-05:00"},
        {"product_id": "P-2", "qty": 1, "promised_at": "2026-10-03T11:00:00-05:00"},
        {"product_id": "P-1", "qty": 1, "promised_at": "2026-10-03T09:45:00-05:00"},
    ]}
    _summarise_bopis(result)
    product, other = result["by_product"]
    assert (product["orders"], product["units"]) == (3, 4)
    assert datetime.fromisoformat(product["earliest_promise"]) == datetime.fromisoformat("2026-10-03T09:30:00-05:00")
    assert datetime.fromisoformat(product["latest_promise"]) == datetime.fromisoformat("2026-10-03T10:00:00-05:00")
    assert other["earliest_promise"] == other["latest_promise"] == "2026-10-03T11:00:00-05:00"
    assert product["promise_times_complete"] and result["by_product_complete"]


def test_missing_times_and_truncated_rows_are_explicit():
    result = {"pending_count": 3, "rows": [
        {"product_id": "P-1", "qty": 2, "promised_at": "2026-10-03T09:30:00-05:00"},
        {"product_id": "P-1", "qty": 1},
    ]}
    _summarise_bopis(result)
    assert not result["by_product_complete"]
    assert not result["by_product"][0]["promise_times_complete"]
    assert result["by_product"][0]["orders"] == 2


def test_empty_demand_has_no_invented_window():
    result = {"pending_count": 0, "rows": []}
    _summarise_bopis(result)
    assert result["by_product"] == []
    assert result["units_total"] == 0
    assert result["by_product_complete"]
