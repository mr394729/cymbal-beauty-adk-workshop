"""Real ADK artifact delivery ends a sole successful call without a second rewrite."""
import pytest
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.apps.app import ResumabilityConfig
from google.adk.runners import InMemoryRunner
from google.genai import types

from agents.cymbal_store_ops.chat_reply import ChatReplyPlugin
from agents.cymbal_store_ops.reports import render
from agents.cymbal_store_ops.tools import end_of_day
from tests.conftest import FakeToolContext
from tests.unit.test_report_delivery import ACTIONS, IDENTITY, ScriptModel, clock_read, reply, run


@pytest.mark.asyncio
@pytest.mark.parametrize('resumable,mixed', [(False, False), (True, False), (True, True)])
async def test_pdf_delivery_keeps_artifact_and_dynamic_actions_without_rewrite(fake_backend, monkeypatch, resumable, mixed):
    async def pdf_bytes(*args):
        return b'%PDF-1.7\nartifact-delivery-test'
    monkeypatch.setattr(render, 'render_pdf', pdf_bytes)
    metrics = (await end_of_day.get_end_of_day_metrics(tool_context=FakeToolContext(IDENTITY)))['rows'][0]
    calls = [types.Part(function_call=types.FunctionCall(name='create_end_of_day_dashboard', id='pdf-current', args={
        'business_date': metrics['business_date'], 'metrics_digest': metrics['metrics_digest'],
        'headline': 'More sales, smaller baskets', 'summary': 'Sales increased while average basket fell.', 'went_well': [], 'follow_up': [], 'next_actions': ACTIONS}))]
    if mixed:
        calls.append(types.Part(function_call=types.FunctionCall(name='clock_read', id='clock-current')))
    responses = [calls]
    if mixed:
        responses.append([reply('The report and clock results are ready.')])
    responses.append([reply('Your next question is independent.')])
    model = ScriptModel(responses=responses)
    app = App(name='artifact_delivery', root_agent=LlmAgent(name='store_manager_agent', model=model,
        tools=[end_of_day.create_end_of_day_dashboard, clock_read]), plugins=[ChatReplyPlugin()],
        resumability_config=ResumabilityConfig(is_resumable=resumable))
    runner = InMemoryRunner(app=app)
    try:
        session = await runner.session_service.create_session(app_name=app.name, user_id='manager', state=IDENTITY)
        events = await run(runner, session, 'Create yesterday\'s report.')
        assert len(model.requests) == (2 if mixed else 1)
        event = next(e for e in events if any(r.name == 'create_end_of_day_dashboard' for r in e.get_function_responses()))
        result = next(r.response for r in event.get_function_responses() if r.name == 'create_end_of_day_dashboard')
        assert result['status'] == 'SUCCESS' and result['reply_completed'] is (not mixed)
        filename = result['artifact']['filename']
        assert event.actions.artifact_delta[filename] == 0
        stored = await runner.artifact_service.load_artifact(app_name=app.name, user_id='manager',
            session_id=session.id, filename=filename, version=0)
        assert stored.inline_data.data.startswith(b'%PDF-')
        public = [p.text for e in events for p in (e.content.parts if e.content else []) if p.text]
        assert len(public) == 1
        if not mixed:
            assert public == ['End-of-day report ready.\n\nSales increased while average basket fell.']
            assert event.actions.state_delta['ui:next_actions'] == ACTIONS
        await run(runner, session, 'What would you check next?')
        assert len(model.requests) == (3 if mixed else 2)
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_invalid_activities_cannot_render_or_publish_artifact(fake_backend, monkeypatch):
    async def forbidden(*args):
        pytest.fail('Invalid activities must fail before rendering')
    monkeypatch.setattr(render, 'render_pdf', forbidden)
    result = await end_of_day.create_end_of_day_dashboard('2026-10-02', 'unused', 'A steady day', 'Sales rose.', [], [], [],
        FakeToolContext(IDENTITY))
    assert result['status'] == 'ERROR' and result['code'] == 'invalid_argument'
