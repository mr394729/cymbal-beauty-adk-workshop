"""Report data loading cannot address or replace operational tables."""

import pytest

from data.load_report_data import KEYS, checked_target, merge_sql, schema_for


def test_only_namespaced_dev_target_and_report_tables_are_allowed():
    assert checked_target("example-project", "demo") == "example-project.cymbal_beauty_demo_dev"
    for ns in ("Demo", "x;DROP", "", "../prod"):
        with pytest.raises(ValueError):
            checked_target("example-project", ns)
    for table in ("store_tasks", "store_inventory", "products", "pos_daily_product_sales;DROP"):
        with pytest.raises(ValueError):
            schema_for(table)


@pytest.mark.parametrize("name", list(KEYS))
def test_merge_updates_only_supplied_keys_and_never_deletes(name):
    sql = merge_sql(checked_target("example-project", "demo"), name)
    assert sql.startswith("MERGE `example-project.cymbal_beauty_demo_dev.")
    assert "JSON_QUERY_ARRAY(@rows)" in sql
    for key in KEYS[name]:
        assert f"target.{key}=source.{key}" in sql
    assert "WHEN NOT MATCHED THEN INSERT" in sql
    assert "DELETE" not in sql and "TRUNCATE" not in sql and "REPLACE" not in sql
    assert "NOT MATCHED BY SOURCE" not in sql
