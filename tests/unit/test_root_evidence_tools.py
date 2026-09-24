"""Direct evidence choices preserve source meaning and the same store/role boundary."""
import json
from copy import deepcopy

import pytest
from google.adk.tools import FunctionTool

from agents.cymbal_store_ops.callbacks import enforce_role_before_tool
from agents.cymbal_store_ops.tools import domain_tools as domain
from agents.cymbal_store_ops.tools.data_backend import parse_ts
from agents.cymbal_store_ops.tools.inventory_context import get_inventory_context
from agents.cymbal_store_ops.tools.operations_tools import get_loss_controls, get_merchandising_work
from tests.conftest import FakeToolContext


def context(role='store_manager', user='U-M014', store='S-014'):
    return FakeToolContext({'user:store_id': store, 'user:role': role, 'user:user_id': user})


@pytest.mark.parametrize('function', [domain.get_shrink_signals, domain.get_task_history, get_loss_controls])
def test_manager_reads_reject_associate_and_incomplete_identity_before_backend(fake_backend, function):
    for ctx in (context('associate', 'A-1004'), context(user=''), context(store=''), None):
        assert function(product_id='P-0420', tool_context=ctx)['code'] == 'forbidden'
    assert fake_backend.calls == []
    denied = enforce_role_before_tool(FunctionTool(function), {'product_id': 'P-0420'}, context('associate', 'A-1004'))
    assert denied['status'] == 'ERROR'
    assert function(product_id='P-0420', tool_context=context())['status'] == 'SUCCESS'


@pytest.mark.parametrize('function', [domain.get_shrink_signals, domain.get_task_history])
def test_direct_manager_reads_enforce_explicit_store_even_without_agent_callback(fake_backend, function):
    denied = function(store_id='S-002', tool_context=context())
    assert denied['code'] == 'forbidden' and fake_backend.calls == []
    allowed = function(store_id='S-002', tool_context=context('district_manager', 'U-D001'))
    assert allowed['status'] == 'SUCCESS'
    assert all(args['store_id'] == 'S-002' for _, args in fake_backend.calls)


def test_task_creation_date_cannot_become_completion_evidence(fake_backend):
    task = next(t for t in fake_backend.tasks if t['store_id'] == 'S-014' and t['status'] == 'done')
    task['created_at'] = '2026-10-01T12:00:00-05:00'
    result = domain.get_task_history(tool_context=context())
    row = next(r for r in result['rows'] if r['task_id'] == task['task_id'])
    assert parse_ts(row['created_at']) == parse_ts(task['created_at'])
    assert row['completed_at'] == 'not recorded'


@pytest.mark.asyncio
async def test_inventory_internal_tasks_filter_self_before_paging_and_preserve_manager_view(fake_backend):
    template = dict(fake_backend.tasks[0], product_id='P-0101', store_id='S-014', status='open')
    fake_backend.tasks = [dict(template, task_id=f'T-OTHER-{i:03}', assignee_id='A-1005', note='OTHER-PRIVATE-WORK') for i in range(120)]
    fake_backend.tasks += [dict(template, task_id='T-OWN', assignee_id='A-1004', note='Own assignment'),
                          dict(template, task_id='T-UNASSIGNED', assignee_id=None),
                          dict(template, task_id='T-FOREIGN', store_id='S-002', assignee_id='A-1004')]
    own = (await get_inventory_context('P-0101', context('associate', 'A-1004')))['rows'][0]
    assert [r['task_id'] for r in own['open_tasks']] == ['T-OWN']
    assert own['task_scope'] == 'own_assigned_tasks'
    assert own['task_page'] == {'returned_count': 1, 'total_matching': 1, 'has_more': False}
    assert own['decision']['existing_open_task_count'] == 1
    assert 'OTHER-PRIVATE-WORK' not in json.dumps(own)
    queries = [args for name, args in fake_backend.calls if name == 'query_store_data']
    assert queries[0]['parameters']['scope_user'] == 'A-1004'
    assert 'assignee_id = @scope_user' in queries[0]['query']
    manager = (await get_inventory_context('P-0101', context()))['rows'][0]
    assert manager['task_scope'] == 'store'
    assert any(r['assignee_id'] == 'A-1005' for r in manager['open_tasks'])
    assert all(r['store_id'] == 'S-014' for r in manager['open_tasks'])


@pytest.mark.asyncio
async def test_incomplete_inventory_identity_is_denied_before_any_read(fake_backend):
    for ctx in (context(user=''), context(role='unknown'), None):
        assert (await get_inventory_context('P-0101', ctx))['code'] == 'forbidden'
    assert fake_backend.calls == []


@pytest.mark.asyncio
async def test_source_semantics_do_not_invent_targets_or_change_stored_snapshots(fake_backend):
    original = deepcopy(fake_backend.operations)
    controls = get_loss_controls('P-0420', context())
    checks = controls['rows'][0]['payload']['checks']
    assert checks and all(check['id_type'] == 'inspection_record' for check in checks)
    directive = next(r for r in fake_backend.operations if r['system'] == 'directives')
    payload = json.loads(directive['payload'])
    payload['directives'][0]['due_time'] = '11:15'
    directive['payload'] = json.dumps(payload)
    updated = deepcopy(fake_backend.operations)
    result = get_merchandising_work(context())
    actual = result['rows'][0]['payload']['directives'][0]
    assert all(actual[key] == value for key, value in payload['directives'][0].items())
    assert actual['required_units'] is None and actual['completion_criteria_status'] == 'not_recorded'
    assert '11:15' in json.dumps(result)
    assert 'completion_criteria' in result['field_semantics']
    stock = next(r for r in fake_backend.inventory if r['store_id'] == 'S-014' and r['product_id'] == 'P-0101')
    stock['shelf_capacity'] = 23
    row = (await get_inventory_context('P-0101', context()))['rows'][0]
    assert row['stock']['shelf_capacity'] == 23
    assert 'shelf_capacity' in row['field_semantics']
    assert fake_backend.operations == updated
    before_controls = next(r for r in original if r['system'] == 'loss_controls')
    after_controls = next(r for r in fake_backend.operations if r['system'] == 'loss_controls')
    assert before_controls == after_controls


def test_root_exposes_native_evidence_choices_and_keeps_consultants():
    from agents.cymbal_store_ops.agent import make_root_agent
    root = make_root_agent()
    tools = {getattr(tool, 'name', None) or tool.__name__: tool for tool in root.tools}
    for name in ('get_inventory_context', 'get_shrink_signals', 'get_loss_controls', 'get_task_history'):
        schema = FunctionTool(tools[name])._get_declaration().model_dump(mode='json', exclude_none=True)
        assert schema['name'] == name and 'tool_context' not in schema['parameters_json_schema']['properties']
    assert {'inventory_excellence', 'loss_prevention'} <= {a.name for a in root.sub_agents}
