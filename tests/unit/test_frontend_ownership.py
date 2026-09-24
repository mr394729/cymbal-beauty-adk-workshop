"""Exercise HTTP ownership with actual ADK sessions and artifact versioning."""
from types import SimpleNamespace

import httpx
import pytest
from google.adk.artifacts import InMemoryArtifactService
from google.adk.events import Event, EventActions
from google.adk.sessions import InMemorySessionService
from google.genai import types

from frontend import server


@pytest.fixture
def target(monkeypatch):
    target = server.LocalTarget.__new__(server.LocalTarget)
    target.app_name = "cymbal_store_ops"
    target.runner = SimpleNamespace(session_service=InMemorySessionService(), artifact_service=InMemoryArtifactService())
    monkeypatch.setattr(server, "PASSWORD", "test-password")
    monkeypatch.setattr(server, "TARGET", {"kind": "local", "impl": target})
    return target


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test")


async def sign_in(c):
    result = await c.post("/api/login", json={"password": "test-password"})
    assert result.status_code == 200


async def new(c, persona="manager"):
    result = await c.post("/api/sessions", json={"user_id": "attacker-chosen", "demo_identity": persona, "title": "Review stock"})
    assert result.status_code == 200, result.text
    return result.json()["session_id"]


async def test_other_browser_and_persona_cannot_read_or_continue_session(target):
    async with client() as first, client() as second:
        await sign_in(first)
        await sign_in(second)
        sid = await new(first)
        assert (await first.get(f"/api/sessions/{sid}")).status_code == 200
        assert (await second.get(f"/api/sessions/{sid}")).status_code == 404
        assert (await first.get(f"/api/sessions/{sid}?persona=associate")).status_code == 404
        assert (await second.post("/api/chat", json={"session_id": sid, "user_id": "attacker-chosen", "text": "stock"})).status_code == 404
        assert (await second.post("/api/confirm", json={"session_id": sid, "invocation_id": "i", "fc_id": "f", "confirmed": True})).status_code == 404
        assert (await second.get("/api/sessions")).json() == {"sessions": []}
        assert (await first.get("/api/sessions")).json()["sessions"][0]["title"] == "Review stock"
        associate = await new(first, "associate")
        manager_state = (await first.get(f"/api/sessions/{sid}")).json()["state"]
        associate_state = (await first.get(f"/api/sessions/{associate}?persona=associate")).json()["state"]
        assert manager_state["user:role"] == "store_manager"
        assert associate_state["user:role"] == "associate"
        assert "_frontend_owner" not in manager_state


async def test_tampered_cookie_and_password_rotation_reject_browser_identity(target, monkeypatch):
    async with client() as c:
        await sign_in(c)
        c.cookies.set("cymbal_browser", "0" * 32 + ".forged", domain="test.local", path="/")
        assert (await c.get("/api/sessions")).status_code == 401
        await sign_in(c)
        monkeypatch.setattr(server, "PASSWORD", "rotated")
        assert (await c.get("/api/sessions")).status_code == 401


async def test_history_uses_recorded_events_and_does_not_replay_old_approvals(target):
    async with client() as c:
        await sign_in(c)
        sid = await new(c)
        session = next(s for users in target.runner.session_service.sessions.values() for sessions in users.values() for s in sessions.values() if s.id == sid)
        await target.runner.session_service.append_event(session=session, event=Event(
            author="user", invocation_id="turn", content=types.Content(role="user", parts=[types.Part(text="Show stock")])) )
        await target.runner.session_service.append_event(session=session, event=Event(
            author="store_manager_agent", invocation_id="turn", content=types.Content(role="model", parts=[types.Part(text="Six hundred products.")]),
            actions=EventActions(artifact_delta={"report.pdf": 0})))
        result = (await c.get(f"/api/sessions/{sid}")).json()
        assert [e["text"] for e in result["events"] if e["type"] in {"user", "text"}] == ["Show stock", "Six hundred products."]
        assert any(e["type"] == "artifact" for e in result["events"])


async def test_pdf_download_requires_ownership_store_metadata_and_valid_pdf(target):
    async with client() as c, client() as other:
        await sign_in(c)
        await sign_in(other)
        sid = await new(c)
        session = next(s for users in target.runner.session_service.sessions.values() for sessions in users.values() for s in sessions.values() if s.id == sid)
        scope = dict(app_name=target.app_name, user_id=session.user_id, session_id=sid, filename="report.pdf")
        await target.runner.artifact_service.save_artifact(**scope, artifact=types.Part.from_bytes(data=b"%PDF-1.7\nexample", mime_type="application/pdf"), custom_metadata={"store_id": (await target.get_session(session.user_id, sid))["state"]["user:store_id"]})
        url = f"/api/sessions/{sid}/artifacts/report.pdf?version=0"
        assert (await other.get(url)).status_code == 404
        response = await c.get(url)
        assert response.status_code == 200 and response.content.startswith(b"%PDF-")
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["content-type"] == "application/pdf"
        assert (await c.get(url + "&download=true")).headers["content-disposition"].startswith("attachment")
        await target.runner.artifact_service.save_artifact(**scope, artifact=types.Part.from_bytes(data=b"%PDF-1.7", mime_type="application/pdf"), custom_metadata={"store_id": "another-store"})
        assert (await c.get(url.replace("version=0", "version=1"))).status_code == 404
        assert (await c.get(f"/api/sessions/{sid}/artifacts/report.pdf?version=-1")).status_code == 400


@pytest.mark.parametrize("code,message,missing", [
    (400, "Agent Engine Error: Session 123 does not belong to user browser-other-manager.", True),
    (400, "Agent Engine Error: Session 123 does not belong to user somebody-else.", False),
    (400, "Invalid engine configuration", False),
    (403, "Permission denied", False),
    (404, "Session not found", True),
])
async def test_remote_session_sdk_ownership_error_is_private_404(code, message, missing):
    from google.genai.errors import ClientError

    error = ClientError(code, {"error": {"code": code, "message": message}})

    async def get_session(**kwargs):
        raise error

    target = server.AgentEngineTarget.__new__(server.AgentEngineTarget)
    target._remote = SimpleNamespace(async_get_session=get_session)
    if missing:
        assert await target.get_session("browser-other-manager", "123") is None
    else:
        with pytest.raises(ClientError):
            await target.get_session("browser-other-manager", "123")


async def test_event_endpoints_use_browser_owner_and_reject_foreign_session(target, monkeypatch):
    from agents.cymbal_store_ops.events import api

    submitted, listed, marked = [], [], []

    async def enqueue(owner, persona, session_id, state, request_id):
        if persona != "manager":
            raise PermissionError("Store managers can request event analysis")
        submitted.append((owner, persona, session_id, state, request_id))
        return {"job_id": "a" * 64, "status": "queued"}

    async def notifications(owner, persona):
        listed.append((owner, persona))
        return {"notifications": []}

    async def mark(owner, persona, job_id):
        marked.append((owner, persona, job_id))
        return False

    monkeypatch.setattr(api, "enqueue_event", enqueue)
    monkeypatch.setattr(api, "list_notifications", notifications)
    monkeypatch.setattr(api, "mark_read", mark)
    async with client() as c, client() as other:
        await sign_in(c)
        await sign_in(other)
        sid = await new(c)
        body = {"session_id": sid, "request_id": "review-request", "owner": "forged-owner", "store_id": "S-999"}
        assert (await other.post("/api/events", json=body)).status_code == 404
        assert (await c.post("/api/events", json=body)).status_code == 202
        owner, persona, session_id, state, request_id = submitted[0]
        assert owner == state["_frontend_owner"] and owner != "forged-owner"
        assert persona == "manager" and state["user:store_id"] == "S-014"
        assert (await c.get("/api/notifications")).status_code == 200
        assert listed == [(owner, "manager")]
        assert (await other.post(f'/api/notifications/{"a" * 64}/read')).status_code == 404
        assert marked[0][0] != owner
        associate = await new(c, "associate")
        assert (await c.post("/api/events", json={"session_id": associate, "persona": "associate", "request_id": "review-request"})).status_code == 403


async def test_history_labels_only_trusted_initial_event_and_keeps_recorded_message(target):
    import hashlib

    async with client() as c:
        await sign_in(c)
        sid = await new(c)
        session = next(s for users in target.runner.session_service.sessions.values() for sessions in users.values() for s in sessions.values() if s.id == sid)
        message = 'Review the recorded event. {"orders":[{"order_id":"O-014"}]}'
        session.state["_event_initial_message_sha256"] = hashlib.sha256(message.encode()).hexdigest()
        await target.runner.session_service.append_event(session=session, event=Event(
            author="user", invocation_id="automated", content=types.Content(role="user", parts=[types.Part(text=message)])))
        await target.runner.session_service.append_event(session=session, event=Event(
            author="user", invocation_id="human", content=types.Content(role="user", parts=[types.Part(text="What should I do first?")])) )
        result = (await c.get(f"/api/sessions/{sid}")).json()
        assert result["events"] == [
            {"type": "observation", "text": "Review recorded pickup deadlines."},
            {"type": "user", "text": "What should I do first?"},
        ]
        assert (await target.get_session(session.user_id, sid))["events"][0]["content"]["parts"][0]["text"] == message


@pytest.mark.parametrize("rest_aliases", [False, True])
async def test_history_preserves_trace_tools_artifacts_and_source_keys(target, monkeypatch, rest_aliases):
    async with client() as c:
        await sign_in(c)
        sid = await new(c)
        session = next(s for users in target.runner.session_service.sessions.values()
                       for sessions in users.values() for s in sessions.values() if s.id == sid)
        span = {"id": "actual-read", "invocation_id": "turn", "root_invocation_id": "turn",
                "agent": "store_manager_agent", "name": "read_stock", "kind": "tool",
                "start_ms": 1000, "duration_ms": 20, "status": "ok"}
        recorded = [
            Event(author="user", invocation_id="turn", content=types.Content(role="user", parts=[types.Part(text="Read stock")])),
            Event(author="store_manager_agent", invocation_id="turn", content=types.Content(role="model", parts=[
                types.Part(function_call=types.FunctionCall(name="read_stock", id="read", args={"productCode": "P-1"}))])),
            Event(author="store_manager_agent", invocation_id="turn", content=types.Content(role="user", parts=[
                types.Part(function_response=types.FunctionResponse(name="read_stock", id="read", response={
                    "status": "SUCCESS", "rows": [{"productCode": "P-1", "unitsOnHand": 7}]}))]),
                actions=EventActions(state_delta={"ui:trace:store_manager_agent": {
                    "root_invocation_id": "turn", "invocation_id": "turn", "spans": [span]}})),
            Event(author="store_manager_agent", invocation_id="turn", content=types.Content(role="model", parts=[types.Part(text="Seven units.")]),
                  actions=EventActions(artifact_delta={"report.pdf": 0})),
        ]
        for event in recorded:
            await target.runner.session_service.append_event(session=session, event=event)
        original = target.get_session

        async def get_session(user_id, session_id):
            value = await original(user_id, session_id)
            if value is not None and rest_aliases:
                value["events"] = [Event.model_validate(event).model_dump(mode="json", by_alias=True)
                                   for event in value["events"]]
            return value

        monkeypatch.setattr(target, "get_session", get_session)
        response = await c.get(f"/api/sessions/{sid}")
        assert response.status_code == 200
        events = response.json()["events"]
        assert [event["text"] for event in events if event["type"] == "text"] == ["Seven units."]
        call = next(event for event in events if event["type"] == "tool_call")
        assert call["args"] == {"productCode": "P-1"}
        result = next(event for event in events if event["type"] == "tool_result")
        assert result["data"]["rows"] == [{"productCode": "P-1", "unitsOnHand": 7}]
        trace = next(event for event in events if event["type"] == "trace")
        assert trace["spans"][0]["id"] == "actual-read"
        assert trace["spans"][0]["duration_ms"] == 20
        assert any(event["type"] == "artifact" and event["filename"] == "report.pdf" for event in events)


async def test_remote_camel_session_metadata_sorts_history_and_preserves_owned_artifacts(target, monkeypatch):
    from copy import deepcopy

    async with client() as browser, client() as other:
        await sign_in(browser)
        await sign_in(other)
        created = await new(browser)
        local = next(s for users in target.runner.session_service.sessions.values()
                     for sessions in users.values() for s in sessions.values() if s.id == created)
        trusted_state = (await target.get_session(local.user_id, created))["state"]
        nested = {"lastUpdateTime": "business value, not session metadata", "rows": [
            {"productCode": "P-1", "availableUnits": None, "isAvailable": False}],
            "nestedState": {"recordedAt": "2026-10-03T09:00:00-05:00"}}

        def record(sid, updated, title, **state_changes):
            return {"id": sid, "appName": target.app_name, "userId": local.user_id,
                    "lastUpdateTime": updated,
                    "state": {**deepcopy(trusted_state), "ui:conversation_title": title,
                              "businessState": deepcopy(nested), **state_changes}, "events": []}

        older = record("older-session", 1790041000.125, "Older")
        newer = record("newer-session", 1790042000.5, "Newer")
        foreign = record("foreign-session", 1790044000, "Private", _frontend_owner="another-browser")
        associate = record("associate-session", 1790045000, "Associate", _frontend_persona="associate")
        newer["events"] = [Event(author="store_manager_agent", invocation_id="recorded-turn",
            content=types.Content(role="model", parts=[types.Part(text="The report is ready.")]),
            actions=EventActions(artifact_delta={"report.pdf": 0}, state_delta={"businessState": nested})
        ).model_dump(mode="json", by_alias=True)]
        source = [older, foreign, newer, associate]
        before = deepcopy(source)

        async def list_remote_sessions(**kwargs):
            assert kwargs["user_id"] == local.user_id
            return {"sessions": source}

        async def get_remote_session(**kwargs):
            return next((row for row in source if row["id"] == kwargs["session_id"]), None)

        remote = server.AgentEngineTarget.__new__(server.AgentEngineTarget)
        remote._remote = SimpleNamespace(async_get_session=get_remote_session, async_list_sessions=list_remote_sessions)
        monkeypatch.setattr(server, "TARGET", {"kind": "agent-engine", "impl": remote})
        monkeypatch.setattr(server, "artifact_service", lambda: target.runner.artifact_service)
        pdf = b"%PDF-1.7\nOriginal scoped artifact"
        await target.runner.artifact_service.save_artifact(app_name=target.app_name, user_id=local.user_id,
            session_id="newer-session", filename="report.pdf", artifact=types.Part.from_bytes(data=pdf, mime_type="application/pdf"),
            custom_metadata={"store_id": trusted_state["user:store_id"]})

        listing = (await browser.get("/api/sessions")).json()["sessions"]
        assert [(row["session_id"], row["last_update_time"]) for row in listing] == [
            ("newer-session", 1790042000.5), ("older-session", 1790041000.125)]
        normalized = await remote.get_session(local.user_id, "newer-session")
        assert normalized["app_name"] == target.app_name and normalized["user_id"] == local.user_id
        assert normalized["state"]["businessState"] == nested
        assert normalized["events"][0]["actions"]["state_delta"]["businessState"] == nested
        history = (await browser.get("/api/sessions/newer-session")).json()
        assert history["state"]["businessState"] == nested
        assert any(event["type"] == "artifact" and event["filename"] == "report.pdf" for event in history["events"])
        artifact_url = "/api/sessions/newer-session/artifacts/report.pdf?version=0"
        assert (await browser.get(artifact_url)).content == pdf
        assert (await other.get(artifact_url)).status_code == 404
        assert (await browser.get(artifact_url + "&persona=associate")).status_code == 404
        assert (await browser.get("/api/sessions/foreign-session")).status_code == 404
        assert await remote.get_session(local.user_id, "missing-session") is None
        assert source == before, "Normalization modified the original REST payload"
