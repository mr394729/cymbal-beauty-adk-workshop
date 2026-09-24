"""Final reports preserve actual tool evidence and end only a successful sole root call."""
import json
from types import SimpleNamespace

import pytest
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.apps.app import ResumabilityConfig
from google.adk.events import Event, EventActions
from google.adk.models import LlmResponse
from google.adk.models.base_llm import BaseLlm
from google.adk.runners import InMemoryRunner
from google.adk.tools import FunctionTool
from google.genai import types
from pydantic import Field

from agents.cymbal_store_ops.chat_reply import ChatReplyPlugin
from agents.cymbal_store_ops.tools.report_delivery import (
    _sole_current_call,
    deliver_store_report,
    describe_store_data,
    query_store_data,
)
from tests.conftest import FakeToolContext

IDENTITY = {'user:store_id': 'S-014', 'user:role': 'store_manager', 'user:user_id': 'U-M014'}
ACTIONS = [
    {'label': 'Compare categories', 'prompt': 'Compare recorded inventory across categories.'},
    {'label': 'Review skincare', 'prompt': 'Show the skincare inventory records.'},
    {'label': 'Review pickup workload', 'prompt': 'What pickup work is currently pending?'},
]


class ScriptModel(BaseLlm):
    model: str = 'report-test-model'
    responses: list = Field(default_factory=list)
    requests: list = Field(default_factory=list)

    async def generate_content_async(self, llm_request, stream=False):
        index = len(self.requests)
        self.requests.append(llm_request.model_copy(deep=True))
        assert index < len(self.responses), 'Unexpected extra model call after terminal report'
        yield LlmResponse(content=types.Content(role='model', parts=self.responses[index]))


def report_call(**overrides):
    return types.Part(function_call=types.FunctionCall(name='deliver_store_report', id='report-current',
        args={'resource': 'inventory', 'next_actions': ACTIONS, **overrides}))


def reply(text):
    return types.Part(text=json.dumps({'answer': text, 'next_actions': ACTIONS}))


def clock_read() -> dict:
    """A separate ordinary read for the mixed-batch test."""
    return {'status': 'SUCCESS', 'rows': [{'hour': 9}]}


def runner_for(model, resumable=True):
    agent = LlmAgent(name='store_manager_agent', model=model,
                     tools=[deliver_store_report, clock_read])
    return InMemoryRunner(app=App(name='report_tests', root_agent=agent, plugins=[ChatReplyPlugin()],
                                  resumability_config=ResumabilityConfig(is_resumable=resumable)))


async def run(runner, session, text):
    return [event async for event in runner.run_async(user_id=session.user_id, session_id=session.id,
        new_message=types.Content(role='user', parts=[types.Part(text=text)]))]


def report_event(events):
    return next(event for event in events if any(part.function_response and part.function_response.name == 'deliver_store_report'
                for part in (event.content.parts if event.content else [])))


@pytest.mark.asyncio
@pytest.mark.parametrize('resumable', [False, True])
async def test_sole_report_stops_model_and_preserves_next_turn_history(fake_backend, resumable):
    model = ScriptModel(responses=[[report_call()], [reply('Your next question is independent.')]])
    runner = runner_for(model, resumable)
    try:
        session = await runner.session_service.create_session(app_name='report_tests', user_id='manager', state=IDENTITY)
        events = await run(runner, session, 'Give me the inventory report.')
        event = report_event(events)
        response = event.get_function_responses()[0].response
        assert len(model.requests) == 1
        assert event.actions.skip_summarization is True and event.is_final_response()
        assert response['row_count'] == 600 and response['report_already_displayed'] is True
        assert response['rows'] == [] and response['reply_completed'] is True
        assert response['final_reply']['call_id'] == event.get_function_responses()[0].id
        assert event.actions.state_delta['ui:next_actions'] == ACTIONS
        assert [part.text for part in event.content.parts if part.text] == ['Inventory report ready: 600 of 600 matching records.']
        assert len(event.actions.state_delta['ui:report']['rows']) == 600
        from frontend.server import sse
        from journeys.run import TurnResult, _read_events
        serialized = [item.model_dump(mode='json', exclude_none=True) for item in events]
        async def stream():
            for item in serialized:
                yield item
        ui = [json.loads(frame.decode().removeprefix('data: ')) async for frame in sse(stream())]
        assert [item['text'] for item in ui if item['type'] == 'text'] == ['Inventory report ready: 600 of 600 matching records.']
        assert any(item['type'] == 'tool_result' and item['name'] == 'deliver_store_report' for item in ui)
        journey = TurnResult(index=1, say='Give me the inventory report.', approve=False)
        _read_events(serialized, journey, set())
        assert journey.final_text == 'Inventory report ready: 600 of 600 matching records.'
        await run(runner, session, 'Now answer a new question.')
        assert len(model.requests) == 2
        history_parts = [part for content in model.requests[1].contents for part in content.parts or []]
        assert any(part.function_response and part.function_response.name == 'deliver_store_report' for part in history_parts)
        assert any(part.text == 'Now answer a new question.' for part in history_parts)
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_mixed_tool_batch_delivers_report_but_keeps_synthesis(fake_backend):
    model = ScriptModel(responses=[[report_call(), types.Part(function_call=types.FunctionCall(name='clock_read', id='clock-current'))],
                                   [reply('Report delivered; the other read is also complete.')]])
    runner = runner_for(model)
    try:
        session = await runner.session_service.create_session(app_name='report_tests', user_id='manager', state=IDENTITY)
        events = await run(runner, session, 'Show the report and check the time.')
        event = report_event(events)
        result = next(response.response for response in event.get_function_responses() if response.name == 'deliver_store_report')
        assert len(model.requests) == 2
        assert not event.actions.skip_summarization and not result['reply_completed']
        assert result['report_already_displayed'] is True and 'final_reply' not in result
        assert not any(part.text for part in event.content.parts)
    finally:
        await runner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('overrides', [{'resource': 'missing'}, {'store_id': 'S-002'}, {'next_actions': []}])
async def test_failed_or_invalid_delivery_does_not_terminate_or_read_outside_scope(fake_backend, overrides):
    model = ScriptModel(responses=[[report_call(**overrides)], [reply('That report could not be produced.')]])
    runner = runner_for(model)
    try:
        session = await runner.session_service.create_session(app_name='report_tests', user_id='manager', state=IDENTITY)
        events = await run(runner, session, 'Request a report.')
        event = report_event(events)
        assert len(model.requests) == 2 and not event.actions.skip_summarization
        assert event.get_function_responses()[0].response['status'] == 'ERROR'
        assert 'ui:report' not in event.actions.state_delta
        assert fake_backend.calls == []
    finally:
        await runner.close()


def test_terminal_gate_rejects_stale_call_invocation_and_confirmation():
    event = Event(author='store_manager_agent', invocation_id='current',
                  content=types.Content(role='model', parts=[report_call()]))
    inv = SimpleNamespace(invocation_id='current', session=SimpleNamespace(events=[event]), user_content=None)
    context = SimpleNamespace(get_invocation_context=lambda: inv, function_call_id='report-current', tool_confirmation=None)
    assert _sole_current_call(context)
    context.function_call_id = 'old-call'
    assert not _sole_current_call(context)
    context.function_call_id = 'report-current'
    inv.invocation_id = 'new-invocation'
    assert not _sole_current_call(context)
    inv.invocation_id = 'current'
    context.tool_confirmation = SimpleNamespace(confirmed=True)
    assert not _sole_current_call(context)


def test_root_read_and_discovery_contracts_keep_generic_query_choice(fake_backend):
    context = FakeToolContext(IDENTITY)
    schema = FunctionTool(query_store_data)._get_declaration().model_dump(mode='json', exclude_none=True)['parameters_json_schema']
    assert 'delivery' not in schema['properties']
    result = query_store_data('inventory', group_by=['category'], measures=[{'operation': 'count'}], tool_context=context)
    assert result['status'] == 'SUCCESS' and sum(row['count_records'] for row in result['rows']) == 600
    assert 'ui:report' not in context.state
    discovery = describe_store_data('reviews', tool_context=context)
    assert set(discovery['query_tools']) == {'query_store_data', 'deliver_store_report'}
    assert 'delivery_modes' not in discovery and 'rating' in discovery['rows'][0]['fields']


@pytest.mark.asyncio
async def test_adapter_does_not_promote_unmatched_or_nonterminal_function_response():
    for skip, invocation, call_id in [(False, 'now', 'call'), (True, 'old', 'call'), (True, 'now', 'old')]:
        event = Event(author='store_manager_agent', invocation_id='now', actions=EventActions(skip_summarization=skip),
            content=types.Content(role='user', parts=[types.Part(function_response=types.FunctionResponse(
                name='deliver_store_report', id='call', response={'status':'SUCCESS','reply_completed':True,
                    'final_reply':{'answer':'Must not display','next_actions':ACTIONS,'invocation_id':invocation,'call_id':call_id}}))]))
        assert await ChatReplyPlugin().on_event_callback(invocation_context=None, event=event) is None
        assert not any(part.text for part in event.content.parts)


@pytest.mark.asyncio
async def test_partial_report_and_two_sessions_do_not_share_completion(fake_backend):
    template = next(row for row in fake_backend.tasks if row['store_id'] == 'S-014')
    fake_backend.tasks = [{**template, 'task_id': f'T-{i:05}'} for i in range(5003)]
    model = ScriptModel(responses=[[report_call(resource='tasks', fields=['task_id'])],
                                   [report_call(resource='inventory', filters=[{'field':'product_id','value':'P-0101'}])]])
    runner = runner_for(model)
    try:
        first = await runner.session_service.create_session(app_name='report_tests', user_id='first', state=IDENTITY)
        second = await runner.session_service.create_session(app_name='report_tests', user_id='second', state=IDENTITY)
        event1 = report_event(await run(runner, first, 'Give me all tasks.'))
        event2 = report_event(await run(runner, second, 'Show this product inventory.'))
        result1 = event1.get_function_responses()[0].response
        result2 = event2.get_function_responses()[0].response
        assert not result1['complete'] and result1['row_count'] == 5000 and result1['total_matching'] == 5003
        assert 'partial' in result1['final_reply']['answer']
        assert result2['complete'] and result2['row_count'] == 1
        assert result1['report_id'] != result2['report_id']
        assert result1['final_reply']['invocation_id'] != result2['final_reply']['invocation_id']
        assert len(model.requests) == 2
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_source_failure_keeps_synthesis_active(fake_backend, monkeypatch):
    from google.api_core.exceptions import ServiceUnavailable
    def unavailable(*args, **kwargs):
        raise ServiceUnavailable('Source unavailable')
    monkeypatch.setattr(fake_backend, '_log', unavailable)
    model = ScriptModel(responses=[[report_call()], [reply('The source is unavailable.')]])
    runner = runner_for(model)
    try:
        session = await runner.session_service.create_session(app_name='report_tests', user_id='manager', state=IDENTITY)
        event = report_event(await run(runner, session, 'Show inventory.'))
        assert event.get_function_responses()[0].response['code'] == 'source_unavailable'
        assert not event.actions.skip_summarization and len(model.requests) == 2
    finally:
        await runner.close()
