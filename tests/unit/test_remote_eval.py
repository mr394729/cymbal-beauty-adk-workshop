"""Remote release probes accept evidence paths without relaxing approval boundaries."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from deployment.remote_eval import assess, collect

PROBES = {p['id']: p for p in json.loads(Path('eval/golden_prompts.json').read_text())['prompts']}


def tool_is_mcp(name):
    return name.startswith("store_mcp_")


def evidence(name, args=None, status='SUCCESS', call_id='one', response_id='one', text='7 units on hand'):
    return collect([{'content': {'parts': [
        {'function_call': {'id': call_id, 'name': name, 'args': args or {}}},
        {'function_response': {'id': response_id, 'name': name, 'response': ({'structuredContent': {'status': status}, 'isError': False} if tool_is_mcp(name) else {'status': status})}},
        {'text': text}]}}])


@pytest.mark.parametrize('tool,args', [('get_inventory_context', {}), ('check_store_stock', {}),
    ('query_store_data', {'resource': 'inventory'}), ('store_mcp_query_store_data', {'resource': 'inventory'})])
def test_alternative_actual_reads_pass_same_factual_assertion(tool, args):
    assert assess(PROBES['osa_explanation'], evidence(tool, args))['ok']


@pytest.mark.parametrize('tool,args,status,match', [('inventory_excellence', {}, 'SUCCESS', True),
    ('describe_store_data', {}, 'SUCCESS', True), ('query_store_data', {'resource': 'invented'}, 'SUCCESS', True),
    ('check_store_stock', {}, 'ERROR', True), ('check_store_stock', {}, 'SUCCESS', False)])
def test_wrapper_schema_failure_or_unmatched_response_is_not_read_evidence(tool, args, status, match):
    got = assess(PROBES['osa_explanation'], evidence(tool, args, status, response_id='one' if match else 'different'))
    assert not got['ok']
    assert 'missing_successful_store_read' in got['failures']


def test_identity_and_answer_facts_still_required():
    assert assess(PROBES['manager_identity'], evidence('identify_demo_user', text='Hello Dana'))['ok']
    assert not assess(PROBES['manager_identity'], evidence('get_inventory_context', text='Hello Dana'))['ok']
    assert not assess(PROBES['osa_explanation'], evidence('check_store_stock', text='12 units on hand'))['ok']


def test_approval_requires_actual_pause_and_no_successful_write():
    probe = PROBES['task_approval_hitl']
    assert not assess(probe, evidence('store_tasks', text='Please approve'))['ok']
    paused = collect([{'long_running_tool_ids': ['approve'], 'content': {'parts': [
        {'function_call': {'id': 'approve', 'name': 'adk_request_confirmation', 'args': {}}}]}}])
    assert assess(probe, paused)['ok']
    write = evidence('create_store_task')
    assert not assess(probe, (write[0], write[1], paused[2], 'Done'))['ok']
    assert not assess(PROBES['blocked_write'], write)['ok']


def test_smoke_transport_preserves_revision_identity_and_uses_shared_decoder(monkeypatch):
    from deployment.smoke import stream_events
    seen = []

    class Target:
        api_resource = SimpleNamespace(name='projects/p/locations/us-central1/reasoningEngines/e/runtimeRevisions/7')

        async def async_create_session(self, **kwargs):
            seen.append(kwargs)
            return {'id': 'session-one'}

    async def stream_query(**kwargs):
        seen.append(kwargs)
        yield {'content': {'parts': [{'text': 'Actual response'}]}}

    monkeypatch.setattr('deployment.streaming.stream_query', stream_query)
    assert stream_events(Target(), 'Question', 'user-one')[0]['content']['parts'][0]['text'] == 'Actual response'
    assert seen == [{'user_id': 'user-one'}, {'name': Target.api_resource.name,
        'user_id': 'user-one', 'session_id': 'session-one', 'message': 'Question'}]


def test_actual_mcp_envelope_errors_and_smoke(monkeypatch):
    from deployment.smoke import stream
    events = [{'content': {'parts': [
        {'function_call': {'name': 'store_mcp_get_product_stock', 'id': 'stock', 'args': {}}},
        {'function_response': {'name': 'store_mcp_get_product_stock', 'id': 'stock', 'response':
            {'structuredContent': {'status': 'SUCCESS', 'store_on_hand': 7}, 'isError': False}}},
        {'text': '7 units on hand'}]}}]
    monkeypatch.setattr('deployment.smoke.stream_events', lambda *args: events)
    assert stream(None, 'Stock')[2:] == ([], ['store_mcp_get_product_stock'])
    assert assess(PROBES['osa_explanation'], collect(events))['ok']
    events[0]['content']['parts'][1]['function_response']['response']['isError'] = True
    assert stream(None, 'Stock')[2:] == (['store_mcp_get_product_stock'], [])
    assert not assess(PROBES['osa_explanation'], collect(events))['ok']
