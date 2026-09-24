"""Operational exceptions, empty searches and missing records have distinct meanings."""
import pytest

from agents.cymbal_store_ops.tools.domain_tools import get_shrink_signals
from agents.cymbal_store_ops.tools.inventory_context import get_inventory_context
from agents.cymbal_store_ops.tools.operations_tools import (
    get_loss_controls,
    get_loss_reconciliation,
)
from tests.conftest import FakeToolContext


def context():
    return FakeToolContext({'user:user_id': 'U-M014', 'user:store_id': 'S-014', 'user:role': 'store_manager'})


@pytest.mark.asyncio
@pytest.mark.parametrize('shelf,back,expected', [
    (0, 7, ['empty_shelf_with_store_stock', 'below_reorder_point']),
    (2, 18, []), (0, 20, ['empty_shelf_with_store_stock']),
    (1, 0, ['below_reorder_point']), (0, 0, ['below_reorder_point']),
])
async def test_availability_flags_follow_changed_stock_separately_from_evidence_gaps(fake_backend, shelf, back, expected):
    stock = next(r for r in fake_backend.inventory if r['store_id'] == 'S-014' and r['product_id'] == 'P-0101')
    stock.update(on_shelf_qty=shelf, backroom_qty=back, on_hand=shelf + back)
    result = await get_inventory_context('P-0101', context())
    assert result['status'] == 'SUCCESS'
    assert result['rows'][0]['availability_flags'] == expected
    assert 'evidence_gaps' in result['rows'][0]['decision']
    assert 'reasons' not in result['rows'][0]['decision']


def test_complete_empty_loss_search_is_explicit_zero_in_its_recorded_scope(fake_backend):
    fake_backend.shrink[:] = [r for r in fake_backend.shrink if r['product_id'] != 'P-0101']
    result = get_shrink_signals('P-0101', tool_context=context())
    assert result['complete'] and result['returned_group_count'] == 0
    assert result['recorded_totals'] == {'events': 0, 'units': 0, 'value_usd': 0.0}
    assert result['query_scope']['product_id'] == 'P-0101'
    assert result['query_scope']['store_id'] == 'S-014'
    assert result['query_scope']['window_start'] < result['query_scope']['window_end']


def test_capped_loss_groups_do_not_become_complete_totals(fake_backend):
    fake_backend.limit = 1
    result = get_shrink_signals(tool_context=context())
    assert result['returned_group_count'] == 1
    assert not result['complete'] and result['recorded_totals'] is None
    assert result['products']


@pytest.mark.parametrize('tool', [get_loss_controls, get_loss_reconciliation])
def test_missing_snapshot_does_not_claim_zero_loss(tool, fake_backend):
    result = tool('P-0101', tool_context=context())
    assert result['status'] == 'SUCCESS' and result['record_status'] == 'not_recorded'
    assert result['record_count'] == 0 and result['query_scope']['product_id'] == 'P-0101'
    assert 'recorded_totals' not in result
    recorded = tool('P-0420', tool_context=context())
    assert recorded['record_status'] == 'recorded' and recorded['record_count'] > 0


@pytest.mark.parametrize("events,value,complete,expected", [
    (1, 10, False, "inconclusive"), (1, 10, True, "monitor"),
    (5, 10, False, "investigate"), (1, 700, False, "investigate"),
])
def test_partial_loss_evidence_cannot_establish_monitor_recommendation(fake_backend, monkeypatch, events, value, complete, expected):
    monkeypatch.setattr(fake_backend, "get_shrink_signals", lambda **kwargs: {
        "status": "SUCCESS", "complete": complete, "window_start": "2026-09-19", "window_end": "2026-10-03",
        "rows": [{"product_id": "P-0101", "events": events, "qty": events, "value_usd": value, "event_type": "unknown_loss"}],
    })
    result = get_shrink_signals(tool_context=context())
    assert result["products"][0]["recommendation"] == expected
