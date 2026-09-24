"""Public REST transport regression for quoted braces in captured ADK traces."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest

from deployment.streaming import StreamQueryError, stream_query

NAME = "projects/123/locations/us-central1/reasoningEngines/456"
CAPTURED = json.loads((Path(__file__).parents[1] / "fixtures/runtime_trace_event.json").read_text())


class Credentials:
    def before_request(self, request, method, url, headers):
        assert method == "POST"
        headers["authorization"] = "Bearer never-print-this-test-token"
        headers["x-goog-user-project"] = "test-quota-project"


class Chunks(httpx.AsyncByteStream):
    def __init__(self, payload, width=173):
        self.payload, self.width, self.closed = payload, width, False

    async def __aiter__(self):
        for start in range(0, len(self.payload), self.width):
            yield self.payload[start:start + self.width]
            await asyncio.sleep(0)

    async def aclose(self):
        self.closed = True


async def run(payload, *, status=200, invocation_id=None, message="Morning", width=173):
    requests = []
    chunks = Chunks(payload.encode(), width)

    def handle(request):
        requests.append(request)
        return httpx.Response(status, stream=chunks)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        values = [event async for event in stream_query(name=NAME, user_id="manager", session_id="session",
            message=message, invocation_id=invocation_id, credentials=Credentials(), http_client=client)]
        assert not client.is_closed  # Injected clients remain caller-owned.
    assert chunks.closed
    return values, requests


@pytest.mark.asyncio
@pytest.mark.parametrize("format_name", ["ndjson", "sse", "concatenated"])
async def test_real_captured_trace_and_following_event_survive_quoted_braces(format_name):
    encoded = json.dumps(CAPTURED, ensure_ascii=False)
    assert encoded.count("{") != encoded.count("}")  # Reproduces installed SDK's framing bug.
    following = {"author": "store_manager_agent", "content": {"parts": [{"text": 'Lumière: { braces and "quotes"'}]}}
    if format_name == "sse":
        payload = ": heartbeat\r\nevent: message\r\nid: 1\r\ndata: " + encoded + "\r\n\r\ndata:" + json.dumps(following) + "\r\n\r\n"
    else:
        payload = encoded + ("\n" if format_name == "ndjson" else "") + json.dumps(following)
    values, requests = await run(payload)
    assert values == [CAPTURED, following]
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == f"https://us-central1-aiplatform.googleapis.com/v1beta1/{NAME}:streamQuery?alt=sse"
    assert json.loads(request.content) == {"classMethod": "async_stream_query", "input": {
        "user_id": "manager", "session_id": "session", "message": "Morning"}}
    assert request.headers["authorization"] == "Bearer never-print-this-test-token"
    assert request.headers["x-goog-user-project"] == "test-quota-project"


@pytest.mark.asyncio
async def test_multiline_sse_partial_utf8_and_confirmation_contract():
    payload = 'data: {\r\ndata: "text": "Lumière } { \\\"quoted\\\""\r\ndata: }\r\n\r\n'
    message = {"role": "user", "parts": [{"function_response": {"name": "adk_request_confirmation",
                "id": "approval-1", "response": {"confirmed": False}}}]}
    values, requests = await run(payload, invocation_id="invocation", message=message, width=1)
    assert values == [{"text": 'Lumière } { "quoted"'}]
    assert json.loads(requests[0].content)["input"] == {
        "user_id": "manager", "session_id": "session", "message": message, "invocation_id": "invocation"}


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", ['{"value":', '{"value": nope}', 'data: {"value":\n\n', '{"ok":1}\n{"broken":', '[1,2]',
    '{"error":{"message":"Bearer secret-response-value"}}'])
async def test_invalid_stream_fails_without_exposing_payload(payload):
    with pytest.raises(StreamQueryError) as error:
        await run(payload)
    assert payload not in str(error.value)
    assert "secret-response-value" not in str(error.value)


@pytest.mark.asyncio
async def test_http_error_is_not_retried_and_does_not_echo_credentials():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(403, text="secret-response-value")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(StreamQueryError, match="HTTP 403") as error:
            _ = [event async for event in stream_query(name=NAME, user_id="m", session_id="s", message="test",
                credentials=Credentials(), http_client=client)]
    assert len(requests) == 1
    assert "secret-response-value" not in str(error.value) and "never-print" not in str(error.value)


@pytest.mark.asyncio
async def test_authentication_error_is_sanitized_and_no_request_is_sent():
    class FailingCredentials:
        def before_request(self, *args):
            raise ValueError("Bearer secret-token-value")

    with pytest.raises(StreamQueryError, match="authenticate") as error:
        _ = [event async for event in stream_query(name=NAME, user_id="m", session_id="s", message="test",
                                                   credentials=FailingCredentials())]
    assert "secret-token-value" not in str(error.value)


@pytest.mark.asyncio
async def test_transport_failure_closes_stream_without_replaying_turn():
    requests = []

    class FailingStream(Chunks):
        async def __aiter__(self):
            yield b'{"ok":1}\n'
            raise httpx.ReadError("Bearer sensitive-transport-value")

    chunks = FailingStream(b"")

    def handle(request):
        requests.append(request)
        return httpx.Response(200, stream=chunks)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        received = []
        with pytest.raises(StreamQueryError, match="not retried") as error:
            async for value in stream_query(name=NAME, user_id="m", session_id="s", message="test",
                                            credentials=Credentials(), http_client=client):
                received.append(value)
    assert received == [{"ok": 1}] and len(requests) == 1 and chunks.closed
    assert "sensitive-transport-value" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmed", [False, True])
async def test_frontend_routes_preserve_chat_and_confirmation_identity(monkeypatch, confirmed):
    from deployment import streaming
    from frontend import server

    received = []

    async def capture(**kwargs):
        received.append(kwargs)
        yield {"author": "store_manager_agent", "content": {"parts": [{"text": "Complete."}]}}

    target = server.AgentEngineTarget.__new__(server.AgentEngineTarget)
    target._name, target._remote = NAME, object()  # A resolved target; no cloud calls.
    async def owned_metadata(user_id, session_id):
        return {"id": session_id, "state": {"_frontend_owner": user_id, "_frontend_persona": "manager"}}

    monkeypatch.setattr(target, "get_session", owned_metadata)
    monkeypatch.setattr(streaming, "stream_query", capture)
    monkeypatch.setattr(server, "PASSWORD", "")
    monkeypatch.setattr(server, "TARGET", {"kind": "agent-engine", "impl": target})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
        assert (await client.get("/api/config")).status_code == 200
        from frontend.session_access import COOKIE
        trusted_user = "browser-" + client.cookies[COOKIE].split(".")[0] + "-manager"
        normal = await client.post("/api/chat", json={"user_id": "manager-17", "session_id": "session-29",
                                                       "text": 'Check Lumière { stock } "now".'})
        confirmation = await client.post("/api/confirm", json={"user_id": "manager-17", "session_id": "session-29",
            "invocation_id": "original-invocation", "fc_id": "original-call", "confirmed": confirmed})
    assert normal.status_code == confirmation.status_code == 200
    assert received == [
        {"name": NAME, "user_id": trusted_user, "session_id": "session-29",
         "message": 'Check Lumière { stock } "now".', "invocation_id": None},
        {"name": NAME, "user_id": trusted_user, "session_id": "session-29", "invocation_id": "original-invocation",
         "message": {"role": "user", "parts": [{"function_response": {"id": "original-call",
            "name": "adk_request_confirmation", "response": {"confirmed": confirmed}}}]}},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmed", [False, True])
async def test_remote_journey_preserves_chat_and_confirmation_identity(monkeypatch, confirmed):
    from deployment import streaming
    from journeys.run import RemoteTarget

    received = []
    response = {"author": "store_manager_agent", "actions": {"state_delta": {"ui:next_actions": []}}}

    async def capture(**kwargs):
        received.append(kwargs)
        yield response

    monkeypatch.setattr(streaming, "stream_query", capture)
    target = RemoteTarget.__new__(RemoteTarget)
    target.name = NAME
    normal = [event async for event in target.stream("associate-4", "session-7", "My current work?", None)]
    resumed = [event async for event in target.stream("associate-4", "session-7",
        {"fc_id": "approval-9", "confirmed": confirmed}, "original-invocation")]
    assert normal == resumed == [response]
    assert received == [
        {"name": NAME, "user_id": "associate-4", "session_id": "session-7",
         "message": "My current work?", "invocation_id": None},
        {"name": NAME, "user_id": "associate-4", "session_id": "session-7", "invocation_id": "original-invocation",
         "message": {"role": "user", "parts": [{"function_response": {"id": "approval-9",
            "name": "adk_request_confirmation", "response": {"confirmed": confirmed}}}]}},
    ]


@pytest.mark.asyncio
async def test_runtime_revision_uses_exact_revision_rest_endpoint():
    revision = NAME + '/runtimeRevisions/7'
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, text='data: {"author":"store_manager_agent"}\n\n')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = [event async for event in stream_query(name=revision, user_id='user', session_id='session',
            message='Read stock', credentials=Credentials(), http_client=client)]
    assert result == [{'author': 'store_manager_agent'}]
    assert requests[0].url.path == f'/v1beta1/{revision}:streamQuery'
