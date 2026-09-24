"""A focused stock API returns current recorded balances without extra investigations."""
from agents.cymbal_store_ops.tools.inventory_summary import get_product_stock
from tests.conftest import FakeToolContext


def manager(store='S-014'):
    return FakeToolContext(state={'user:user_id': 'U-M014', 'user:store_id': store, 'user:role': 'store_manager'})


def test_single_sku_balances_follow_changed_source_rows(fake_backend):
    row = next(r for r in fake_backend.inventory if r['store_id'] == 'S-014' and r['product_id'] == 'P-0135')
    row.update(on_hand=83, on_shelf_qty=31, backroom_qty=52)
    result = get_product_stock('P-0135', manager())
    assert result['status'] == 'SUCCESS' and result['record_found']
    assert len(result['rows']) == 1
    actual = result['rows'][0]
    assert (actual['on_hand'], actual['on_shelf_qty'], actual['backroom_qty']) == (83, 31, 52)
    assert 'reserved_units' not in actual
    assert 'recommended_actions' not in actual


def test_missing_sku_is_absent_not_a_zero_balance(fake_backend):
    result = get_product_stock('P-9999', manager())
    assert result['status'] == 'SUCCESS' and result['record_found'] is False
    assert result['rows'] == []


def test_stock_requires_signed_in_store(fake_backend):
    result = get_product_stock('P-0135', FakeToolContext())
    assert result['status'] == 'ERROR'
