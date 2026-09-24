import pytest

from agents.cymbal_store_ops.tools.sql_guard import SqlGuardError, assert_select_only

P = ("proj.cymbal_beauty_dev",)


@pytest.mark.parametrize("sql", [
    "SELECT product_id FROM `proj.cymbal_beauty_dev.products` LIMIT 5",
    "WITH t AS (SELECT * FROM proj.cymbal_beauty_dev.stores) SELECT city FROM t",
    "select name from `proj.cymbal_beauty_dev.products` where price_usd < 30 -- cheap",
    "SELECT 1",
])
def test_allows_read_only(sql):
    assert assert_select_only(sql, P)


@pytest.mark.parametrize("sql,fragment", [
    ("DELETE FROM `proj.cymbal_beauty_dev.reviews` WHERE 1=1", "only SELECT"),
    ("UPDATE proj.cymbal_beauty_dev.products SET price_usd = 1", "only SELECT"),
    ("SELECT 1; DROP TABLE proj.cymbal_beauty_dev.products", "multiple statements"),
    ("SELECT * FROM proj.cymbal_beauty_dev.products WHERE name = 'x' UNION ALL SELECT * FROM proj.other_ds.coaching_signals", "people data|outside the allowed"),
    ("SELECT * FROM proj.cymbal_beauty_dev.INFORMATION_SCHEMA.TABLES", "INFORMATION_SCHEMA"),
    ("SELECT * FROM proj.cymbal_beauty_dev.associates", "people data|outside the allowed"),
    ("", "empty"),
    ("SELECT * FROM proj.cymbal_beauty_dev.products; EXECUTE IMMEDIATE 'x'", "multiple statements"),
])
def test_rejects_everything_else(sql, fragment):
    with pytest.raises(SqlGuardError, match=fragment):
        assert_select_only(sql, P)


def test_keywords_inside_string_literals_are_ignored():
    assert assert_select_only("SELECT * FROM proj.cymbal_beauty_dev.products WHERE name = 'DELETE me'", P)
