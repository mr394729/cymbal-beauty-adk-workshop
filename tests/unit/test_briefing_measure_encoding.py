"""Writer evidence remains reconstructable; operational schedules remain paired."""
import json
from copy import deepcopy

import pytest

from agents.cymbal_store_ops.sub_agents.briefing_facts import project_briefing_facts, writer_facts
from agents.cymbal_store_ops.tools import domain_tools as domain
from tests.conftest import FakeToolContext
from tests.unit.test_briefing_signals import MANAGER, branch, outputs, run, tool_events


def restore_products(value):
    products = deepcopy(value['products'])
    encoding = value.get('product_measure_encoding')
    for product in products:
        components = product.pop('recorded_event_type_breakdown')
        if encoding:
            product['qty'] = product.pop('units')
            product['total_recorded_units'] = product['qty']
            counts = {}
            for row in components:
                counts[row['event_type']] = counts.get(row['event_type'], 0) + row['units']
            product['units_by_type'] = counts
            product['unknown_loss_units'] = counts.get('unknown_loss', 0)
            if 'shared_quantity_description' in encoding:
                product['quantity_description'] = encoding['shared_quantity_description']
    return products


def source_facts():
    raw = domain.get_shrink_signals(tool_context=FakeToolContext(dict(MANAGER)))
    return project_briefing_facts('shrink', {'get_shrink_signals': raw})


def bytesize(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode())


def test_real_loss_snapshot_canonical_measures_preserve_every_product(fake_backend):
    facts = source_facts()
    source = facts['get_shrink_signals']
    source['products'][-1]['future_evidence'] = {'source_id': 'unchanged', 'unknown': None}
    source['rows'][-1]['source_record_id'] = 'retained-component-link'
    before = deepcopy(facts)
    value = writer_facts('shrink', facts)['get_shrink_signals']
    assert facts == before
    assert restore_products(value) == source['products']
    assert len(value['products']) == len(source['products'])
    assert sum(len(p['recorded_event_type_breakdown']) for p in value['products']) == len(source['rows'])
    assert any(row.get('source_record_id') == 'retained-component-link'
               for p in value['products'] for row in p['recorded_event_type_breakdown'])
    # Compare the same explicit joined representation, with and without alias factoring.
    no_alias = deepcopy(value)
    for projected, original in zip(no_alias['products'], source['products'], strict=True):
        components = projected['recorded_event_type_breakdown']
        projected.clear()
        projected.update(deepcopy(original), recorded_event_type_breakdown=components)
    del no_alias['product_measure_encoding']
    assert bytesize(value) < bytesize(no_alias) * .85
    for product in value['products']:
        assert product['units'] == sum(c['units'] for c in product['recorded_event_type_breakdown'])
        assert product['events'] == sum(c['events'] for c in product['recorded_event_type_breakdown'])


@pytest.mark.parametrize('mutation', [
    lambda s: s.update(complete=False),
    lambda s: s['products'][0].update(total_recorded_units=999),
    lambda s: s['products'][0].update(unknown_loss_units=None),
    lambda s: s['products'][0].update(units_by_type={'unknown_loss': False}),
    lambda s: s['products'][0].update(qty=7.0),
    lambda s: s['products'][0].update(units='future source meaning'),
    lambda s: s['products'][0].pop('total_recorded_units'),
    lambda s: s['rows'][0].update(qty=False),
    lambda s: s.update(product_measure_encoding={'future_metadata': True}),
])
def test_partial_disagreeing_or_unknown_alias_contract_is_not_compacted(fake_backend, mutation):
    facts = source_facts()
    source = facts['get_shrink_signals']
    mutation(source)
    value = writer_facts('shrink', facts)['get_shrink_signals']
    assert restore_products({**value, 'product_measure_encoding': None}) == source['products']
    assert value.get('product_measure_encoding') == source.get('product_measure_encoding')


def test_differing_measure_descriptions_are_not_hidden(fake_backend):
    facts = source_facts()
    facts['get_shrink_signals']['products'][1]['quantity_description'] = 'Different source caveat'
    value = writer_facts('shrink', facts)['get_shrink_signals']
    assert 'shared_quantity_description' not in value['product_measure_encoding']
    assert restore_products(value) == facts['get_shrink_signals']['products']


@pytest.mark.asyncio
async def test_writer_projection_never_changes_authoritative_trace(fake_backend):
    events = await run(branch('shrink'), MANAGER)
    _, responses = tool_events(events)
    before = [r.model_dump(mode='json') for r in responses]
    facts = outputs(events)['temp:briefing_shrink']
    value = writer_facts('shrink', facts)['get_shrink_signals']
    assert value['product_measure_encoding']
    assert [r.model_dump(mode='json') for r in responses] == before
    assert restore_products(value) == facts['get_shrink_signals']['products']


def test_writer_keeps_named_schedule_pairs_and_all_order_constraints():
    orders = [{'order_id': f'O-{i}', 'promised_by': f'10:{i}0', 'units': i+1,
               'estimated_finish': f'09:{i}0', 'within_promise': True} for i in range(3)]
    scenario = {'start': '09:00', 'estimated_queue_finish': '09:54', 'orders': orders,
                'orders_late_in_estimate': 0, 'start_at_or_after_snapshot': True,
                'feasible_from_snapshot': True, 'future_constraint': {'missing': None}}
    later = {**deepcopy(scenario), 'start': '09:24', 'estimated_queue_finish': '10:18'}
    result = {'status': 'SUCCESS', 'rows': [{'orders': orders, 'start': '09:00',
              'estimated_queue_finish': '09:54',
              'schedule_scenarios': {'snapshot_start': scenario, 'latest_uninterrupted_start': later}}]}
    facts = {'get_pickup_workload': result}
    value = writer_facts('coverage', facts)['get_pickup_workload']
    assert value == result and value is not result
    assert value['rows'][0]['schedule_scenarios']['snapshot_start']['orders'] == orders
    assert isinstance(value['rows'][0]['schedule_scenarios']['snapshot_start']['orders'], list)
