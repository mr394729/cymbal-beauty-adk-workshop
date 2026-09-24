"""Missing-feed evaluation changes reads only and accepts independent evidence routes."""
import copy

import pytest
from google.adk.evaluation.eval_case import IntermediateData, Invocation
from google.genai import types

from agents.cymbal_store_ops.tools.backends.bigquery import BigQueryBackend
from agents.cymbal_store_ops.tools.domain_tools import get_bopis_demand
from agents.cymbal_store_ops.tools.store_query import query_store_data
from eval.pickup_fault import expected_totals, missing_pending_feed, pickup_counts_invariant
from tests.conftest import FakeToolContext


def context():
    return FakeToolContext({'user:user_id': 'U-M014', 'user:store_id': 'S-014', 'user:role': 'store_manager'})


def count_query(**kwargs):
    return query_store_data('orders', filters=[{'field': 'status', 'value': 'pending'}],
        measures=[{'operation': 'count'}, {'operation': 'sum', 'field': 'qty'}], tool_context=context(), **kwargs)


def test_fake_native_and_generic_share_fault_then_restore_changed_source(fake_backend):
    original = copy.deepcopy(fake_backend.orders)
    extra = copy.deepcopy(next(r for r in original if r['store_id'] == 'S-014' and r['status'] == 'pending'))
    extra.update(order_id='TEST-NEW-ORDER', qty=17)
    fake_backend.orders.append(extra)
    baseline = count_query()['rows']
    assert baseline == [{'count_records': expected_totals()[0] + 1, 'sum_qty': expected_totals()[1] + 17}]
    source = fake_backend.orders
    with missing_pending_feed(fake_backend):
        assert get_bopis_demand(tool_context=context())['pending_count'] == 0
        assert count_query()['rows'] == [{'count_records': 0, 'sum_qty': None}]
        assert query_store_data('orders', tool_context=context(), store_id='S-001')['status'] == 'ERROR'
    assert fake_backend.orders is source
    assert count_query()['rows'] == baseline
    assert fake_backend.orders[:-1] == original


def test_exception_restores_bq_relation_and_fake_records(fake_backend):
    backend = BigQueryBackend.__new__(BigQueryBackend)
    backend.main = 'project.dataset'
    source = fake_backend.orders
    original = BigQueryBackend._t
    with pytest.raises(RuntimeError, match='interrupt'):
        with missing_pending_feed(fake_backend):
            assert backend._t('bopis_orders') == "(SELECT * FROM `project.dataset.bopis_orders` WHERE status IS DISTINCT FROM 'pending')"
            assert backend._t('store_inventory') == '`project.dataset.store_inventory`'
            raise RuntimeError('interrupt')
    assert BigQueryBackend._t is original
    assert backend._t('bopis_orders') == '`project.dataset.bopis_orders`'
    assert fake_backend.orders is source


def scored(name, args, data, *, response_id='read'):
    actual = Invocation(user_content=types.Content(parts=[types.Part(text='Count pending pickup orders and units')]),
        final_response=types.Content(parts=[types.Part(text='9 orders and 13 units')]),
        intermediate_data=IntermediateData(tool_uses=[types.FunctionCall(id='read', name=name, args=args)],
            tool_responses=[types.FunctionResponse(id=response_id, name=name, response=data)]))
    return pickup_counts_invariant(None, [actual], [actual]).overall_score


def test_generic_aggregate_and_native_paths_both_prove_same_counts(fake_backend):
    generic = count_query()
    assert scored('query_store_data', {'resource': 'orders', 'filters': [{'field': 'status', 'value': 'pending'}],
        'measures': [{'operation': 'count'}, {'operation': 'sum', 'field': 'qty'}]}, generic) == 1
    native = get_bopis_demand(tool_context=context())
    assert scored('get_bopis_demand', {}, native) == 1
    assert scored('get_bopis_demand', {}, native, response_id='different') == 0
    assert scored('get_bopis_demand', {'product_id': 'P-0101'}, native) == 0
    assert scored('get_bopis_demand', {'store_id': 'S-001'}, native) == 0
    with missing_pending_feed(fake_backend):
        assert scored('get_bopis_demand', {}, get_bopis_demand(tool_context=context())) == 0


def test_complete_order_list_passes_but_partial_list_or_changed_units_fails(fake_backend):
    args = {'resource': 'orders', 'fields': ['order_id', 'status', 'qty'],
            'filters': [{'field': 'status', 'value': 'pending'}]}
    data = query_store_data(**args, tool_context=context())
    assert scored('query_store_data', args, data) == 1
    incomplete = copy.deepcopy(data)
    incomplete['has_more'] = True
    assert scored('query_store_data', args, incomplete) == 0
    changed = copy.deepcopy(data)
    changed['rows'][0]['qty'] += 1
    assert scored('query_store_data', args, changed) == 0
    data['status'] = 'ERROR'
    assert scored('query_store_data', args, data) == 0
