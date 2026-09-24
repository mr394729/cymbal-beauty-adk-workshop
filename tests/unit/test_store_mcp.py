# ruff: noqa: E402
"""Real MCP Streamable HTTP transport over ASGI and real FakeBackend relational queries."""
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

STAGE = Path(__file__).resolve().parents[2]
REPO = Path(os.environ.get("CYMBAL_LABS_REPO", str(Path.cwd())))
sys.path[:0] = [str(STAGE), str(REPO)]
import agents.cymbal_store_ops

agents.cymbal_store_ops.__path__.insert(0, str(STAGE / "agents/cymbal_store_ops"))

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from agents.cymbal_store_ops.mcp_auth import Scope, Settings, sign_scope, verify_scope
from agents.cymbal_store_ops.mcp_connection import (
    TOOLS,
    make_header_provider,
    make_operational_mcp_toolset,
)
from agents.cymbal_store_ops.tools import data_backend, domain_tools, store_query
from agents.cymbal_store_ops.tools.backends.fake import FakeBackend
from services.store_mcp.server import create_app

CALLER = "agent-runtime@test-project.iam.gserviceaccount.com"
SETTINGS = Settings("https://store-mcp.example.run.app", "unit-test-secret-value-at-least-32-bytes",
                    frozenset({CALLER}), "demo", "dev")


def principal(**changes):
    now = int(time.time())
    values = dict(user_id="U-M014", store_id="S-014", role="store_manager", namespace="demo",
                  environment="dev", audience=SETTINGS.audience, caller=CALLER,
                  issued_at=now, expires_at=now + 120)
    return Scope(**(values | changes))


def request_headers(scope=None):
    return {"Authorization": "Bearer verified-test-token", "X-Cymbal-Caller-Token": "verified-test-token",
            "X-Cymbal-Session": sign_scope(scope or principal(), SETTINGS.scope_key)}


def caller_verifier(token, audience):
    assert audience == SETTINGS.audience
    if token != "verified-test-token":
        raise ValueError("Bad signature")
    return {"email": CALLER, "email_verified": True}


@pytest.fixture
def backend(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(data_backend, "make_backend", lambda *a, **kw: backend)
    monkeypatch.setattr(domain_tools, "make_backend", lambda *a, **kw: backend)
    return backend


@asynccontextmanager
async def connect(headers=None, verifier=caller_verifier):
    app = create_app(SETTINGS, verifier=verifier)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), headers=headers or request_headers()) as http:
            async with streamable_http_client(SETTINGS.audience + "/mcp", http_client=http) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    yield session


def result(call):
    assert not call.isError, call
    return call.structuredContent or json.loads(call.content[0].text)


@pytest.mark.asyncio
async def test_discovery_real_transport_hides_identity_and_writes(backend):
    async with connect() as session:
        tools = (await session.list_tools()).tools
        assert {tool.name for tool in tools} == set(TOOLS)
        for tool in tools:
            assert tool.annotations.readOnlyHint
            # store_id is how a district manager names another store; the server checks it against the signed role
            assert not {"user_id", "role", "namespace", "sql", "delivery"} & tool.inputSchema["properties"].keys()
        denied = result(await session.call_tool("get_shift_roster", {"store_id": "S-015"}))
        assert denied["status"] == "ERROR", "a store manager must not read another store through MCP"
        schema = result(await session.call_tool("describe_store_data", {"resource": "orders"}))
        assert schema["status"] == "SUCCESS"
        assert "report" not in schema["delivery_modes"]


@pytest.mark.asyncio
async def test_changed_inventory_query_and_catalog_match_direct_reads(backend):
    row = next(r for r in backend.inventory if r["store_id"] == "S-014" and r["product_id"] == "P-0101")
    row.update(on_hand=17, on_shelf_qty=9, backroom_qty=8)
    async with connect() as session:
        got = result(await session.call_tool("get_product_stock", {"product_id": "P-0101"}))
        assert got["rows"][0]["on_hand"] == 17
        args = {"resource": "inventory", "group_by": ["category"], "measures": [{"operation": "sum", "field": "on_hand"}]}
        remote = result(await session.call_tool("query_store_data", args))
        direct = store_query.query_store_data(**args, tool_context=SimpleNamespace(state=principal().state()))
        assert remote == json.loads(json.dumps(direct))
        search = result(await session.call_tool("search_products", {"query_text": "Hydra Cream", "limit": 1}))
        assert search["rows"][0]["product_id"] == "P-0101"
        details = result(await session.call_tool("get_product_details", {"product_id": "P-0101"}))
        assert details["status"] == "SUCCESS"


@pytest.mark.asyncio
async def test_associate_scope_manager_only_loss_and_cross_store_filter(backend):
    scope = principal(role="associate", user_id="A-1004")
    async with connect(request_headers(scope)) as session:
        tasks = result(await session.call_tool("query_store_data", {"resource": "tasks"}))
        assert tasks["scope"] == "own_assigned_tasks"
        assert all(r["assignee_id"] == "A-1004" for r in tasks["rows"])
        forbidden = result(await session.call_tool("query_store_data", {"resource": "loss"}))
        assert forbidden["status"] == "ERROR" and forbidden["code"] == "forbidden"
        injection = result(await session.call_tool("query_store_data", {"resource": "inventory",
            "filters": [{"field": "store_id", "operator": "eq", "value": "S-015"}]}))
        assert injection["status"] == "ERROR" or not injection["rows"]


@pytest.mark.asyncio
async def test_missing_catalog_membership_does_not_disclose_product_details(backend):
    backend.inventory = [r for r in backend.inventory if not (r["store_id"] == "S-014" and r["product_id"] == "P-0101")]
    async with connect() as session:
        got = result(await session.call_tool("get_product_details", {"product_id": "P-0101"}))
        assert got["code"] == "not_found"


@pytest.mark.asyncio
async def test_rejected_headers_do_not_reach_backend(monkeypatch):
    def forbidden_backend(*a, **kw):
        pytest.fail("Authentication failure accessed backend")
    monkeypatch.setattr(data_backend, "make_backend", forbidden_backend)
    app = create_app(SETTINGS, verifier=caller_verifier)
    expired = principal(issued_at=int(time.time()) - 240, expires_at=int(time.time()) - 120)
    variants = [{}, request_headers(principal(namespace="other")),
                request_headers(principal(audience="https://other.run.app")), request_headers(expired),
                request_headers() | {"X-Cymbal-Caller-Token": "forged"},
                request_headers() | {"X-Cymbal-Session": request_headers()["X-Cymbal-Session"] + "x"}]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app)) as client:
        for headers in variants:
            response = await client.post(SETTINGS.audience + "/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "query_store_data", "arguments": {"resource": "inventory"}}})
            assert response.status_code in {401, 403}
            assert SETTINGS.scope_key not in response.text


@pytest.mark.parametrize("changes", [
    lambda now: {"caller": "other@test-project.iam.gserviceaccount.com"}, lambda now: {"environment": "prod"},
    lambda now: {"issued_at": now + 90, "expires_at": now + 180},  # issued in the future, beyond the 15 s skew
    lambda now: {"expires_at": now + 600},  # longer than the 180 s maximum lifetime
])
def test_scope_claim_binding(changes):
    # times are taken when the test runs, not when the module is collected: a suite that takes longer than the
    # 90-second head start would otherwise let the "issued in the future" scope drift into the accepted skew
    with pytest.raises(ValueError):
        verify_scope(sign_scope(principal(**changes(int(time.time()))), SETTINGS.scope_key), SETTINGS, CALLER)


@pytest.mark.asyncio
async def test_header_provider_uses_context_and_isolates_personas():
    provider = make_header_provider(SETTINGS, CALLER, token_provider=lambda: "workload-token")
    a = await provider(SimpleNamespace(state=principal().state()))
    b = await provider(SimpleNamespace(state=principal(user_id="A-1007", role="associate").state()))
    assert verify_scope(a["X-Cymbal-Session"], SETTINGS, CALLER).user_id == "U-M014"
    assert verify_scope(b["X-Cymbal-Session"], SETTINGS, CALLER).user_id == "A-1007"
    assert a["Authorization"] == "Bearer workload-token"
    with pytest.raises(ValueError):
        await provider(SimpleNamespace(state={}))


def test_factory_disables_only_without_any_configuration(monkeypatch):
    for name in ("CYMBAL_MCP_URL", "CYMBAL_MCP_AUDIENCE", "CYMBAL_MCP_SCOPE_KEY", "CYMBAL_MCP_CALLER_SERVICE_ACCOUNT"):
        monkeypatch.delenv(name, raising=False)
    assert make_operational_mcp_toolset() is None
    monkeypatch.setenv("CYMBAL_MCP_URL", SETTINGS.audience + "/mcp")
    with pytest.raises(ValueError, match="Missing MCP"):
        make_operational_mcp_toolset()

@pytest.mark.asyncio
async def test_adk_toolset_reuses_transport_without_losing_session_scope(backend):
    from google.adk.agents import LlmAgent
    from google.adk.agents.invocation_context import InvocationContext
    from google.adk.agents.readonly_context import ReadonlyContext
    from google.adk.sessions import InMemorySessionService
    from google.adk.tools import ToolContext
    from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

    app = create_app(SETTINGS, verifier=caller_verifier)
    def http_factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app), headers=headers, timeout=timeout, auth=auth)
    from agents.cymbal_store_ops.mcp_connection import ScopedMcpToolset

    toolset = ScopedMcpToolset(connection_params=StreamableHTTPConnectionParams(
        url=SETTINGS.audience + "/mcp", httpx_client_factory=http_factory),
        tool_filter=TOOLS,
        header_provider=make_header_provider(SETTINGS, CALLER, lambda: "verified-test-token"))
    sessions = InMemorySessionService()
    agent = LlmAgent(name="mcp_test_agent", model="unused-no-model-call")
    async with app.router.lifespan_context(app):
        try:
            for uid, role in [("U-M014", "store_manager"), ("A-1004", "associate")]:
                session = await sessions.create_session(app_name="mcp_test", user_id=uid,
                    state=principal(user_id=uid, role=role).state())
                inv = InvocationContext(invocation_id="test-" + uid, agent=agent, session=session,
                    session_service=sessions)
                tools = await toolset.get_tools(readonly_context=ReadonlyContext(inv))
                tool = next(t for t in tools if t.name.endswith("query_store_data"))
                raw = await tool.run_async(args={"resource": "tasks"}, tool_context=ToolContext(inv))
                # The toolset returns the tool's own result dict, as a local call would.
                got = raw
                assert got["status"] == "SUCCESS"
                if role == "associate":
                    assert got["scope"] == "own_assigned_tasks"
                    assert all(r["assignee_id"] == uid for r in got["rows"])
                else:
                    assert got["scope"] == "store"
        finally:
            await toolset.close()


@pytest.mark.asyncio
async def test_schema_export_fits_registry_cap(backend, tmp_path):
    async with connect() as session:
        tools = (await session.list_tools()).tools
        from agents.cymbal_store_ops.mcp_connection import registry_toolspec

        encoded = json.dumps(registry_toolspec([t.model_dump(mode="json", exclude_none=True) for t in tools]),
                             separators=(",", ":"))
        assert len(encoded.encode()) <= 10 * 1024
        (tmp_path / "toolspec.offline.json").write_text(encoded + "\n")


@pytest.mark.asyncio
async def test_untrusted_caller_rejected_even_with_valid_scope_signature():
    app = create_app(SETTINGS, verifier=lambda token, audience: {"email": "untrusted@test.iam.gserviceaccount.com",
                                                               "email_verified": True})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app)) as client:
        response = await client.post(SETTINGS.audience + "/mcp", headers=request_headers(), json={})
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_failed_source_is_preserved_not_converted_to_empty_stock(backend, monkeypatch):
    from google.api_core.exceptions import ServiceUnavailable
    def failed(*args, **kwargs):
        raise ServiceUnavailable("synthetic source unavailable")
    monkeypatch.setattr(store_query, "_execute", failed)
    async with connect() as session:
        got = result(await session.call_tool("get_product_stock", {"product_id": "P-0101"}))
        assert got["status"] == "ERROR"
        assert not got.get("record_found")


def test_registry_verification_checks_tools_and_endpoint():
    import importlib.util
    path = STAGE / "deployment/mcp_register.py"
    spec = importlib.util.spec_from_file_location("mcp_registry_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    item = {"interfaces": [{"url": SETTINGS.audience + "/mcp"}], "tools": [{"name": name} for name in TOOLS]}
    assert module.verification(item, SETTINGS.audience + "/mcp", set(TOOLS))
    assert not module.verification(item, "https://other/mcp", set(TOOLS))
    item["tools"].pop()
    assert not module.verification(item, SETTINGS.audience + "/mcp", set(TOOLS))


def test_google_id_token_signature_audience_and_claim_verification():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from google.auth import crypt, jwt

    from agents.cymbal_store_ops.mcp_auth import GoogleCallerVerifier

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                           serialization.PublicFormat.SubjectPublicKeyInfo)
    signer = crypt.RSASigner.from_string(private, key_id="test-key")
    now = int(time.time())
    payload = {"iss": "https://accounts.google.com", "aud": SETTINGS.audience, "sub": "12345",
               "iat": now, "exp": now + 120, "email": CALLER, "email_verified": True}
    token = jwt.encode(signer, payload).decode()
    def certificates(url, method="GET", **kwargs):
        return SimpleNamespace(status=200, data=json.dumps({"test-key": public.decode()}).encode())
    verifier = GoogleCallerVerifier(request=certificates)
    assert verifier(token, SETTINGS.audience)["email"] == CALLER
    with pytest.raises(ValueError):
        verifier(token, "https://wrong-audience.run.app")
    with pytest.raises(ValueError):
        verifier(token[:-8] + "AAAAAAAA", SETTINGS.audience)


def test_deployment_plan_is_private_namespaced_and_pins_secret():
    import importlib.util
    path = STAGE / "deployment/mcp_deploy.py"
    spec = importlib.util.spec_from_file_location("mcp_deploy_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args = SimpleNamespace(namespace="demo", env="dev", project="test-project", region="us-central1",
        audience=SETTINGS.audience, caller_service_account=CALLER, runtime_service_account="mcp@test.iam.gserviceaccount.com",
        image="us-central1-docker.pkg.dev/test-project/images/mcp:v1", scope_secret="mcp-key:7")
    plan = module.plan(args)
    assert "cymbal-store-mcp-demo-dev" in plan
    assert "--no-allow-unauthenticated" in plan
    assert "CYMBAL_MCP_SCOPE_KEY=mcp-key:7" in plan
    assert SETTINGS.scope_key not in " ".join(plan)


def test_configured_app_serializes_without_secret_or_live_token_client(monkeypatch):
    import cloudpickle
    from google.adk.agents import LlmAgent
    from google.adk.apps import App

    from agents.cymbal_store_ops import mcp_connection
    values = {"CYMBAL_MCP_URL": SETTINGS.audience + "/mcp", "CYMBAL_MCP_AUDIENCE": SETTINGS.audience,
              "CYMBAL_MCP_CALLER_SERVICE_ACCOUNT": CALLER, "WORKSHOP_NAMESPACE": "demo", "STORE_OPS_ENV": "dev"}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("CYMBAL_MCP_SCOPE_KEY", raising=False)
    def unexpected_token_provider(audience):
        pytest.fail("Packaging tried to initialize runtime credentials")
    monkeypatch.setattr(mcp_connection, "_runtime_token_provider", unexpected_token_provider)
    toolset = make_operational_mcp_toolset()
    app = App(name="mcp_packaging", root_agent=LlmAgent(name="root", model="unused-no-model-call", tools=[toolset]))
    payload = cloudpickle.dumps(app)
    restored = cloudpickle.loads(payload)
    assert restored.root_agent.tools[0].header_provider.caller == CALLER
    monkeypatch.setenv("CYMBAL_MCP_SCOPE_KEY", "never-serialize-this-secret-value")
    payload_with_local_secret = cloudpickle.dumps(app)
    assert b"never-serialize-this-secret-value" not in payload_with_local_secret


@pytest.mark.asyncio
async def test_runtime_header_provider_resolves_key_only_during_call(monkeypatch):
    from agents.cymbal_store_ops import mcp_connection
    provider = mcp_connection.RuntimeHeaderProvider(SETTINGS.audience, CALLER, "demo", "dev")
    monkeypatch.delenv("CYMBAL_MCP_SCOPE_KEY", raising=False)
    with pytest.raises(RuntimeError, match="pinned runtime secret"):
        await provider(SimpleNamespace(state=principal().state()))
    monkeypatch.setenv("CYMBAL_MCP_SCOPE_KEY", SETTINGS.scope_key)
    monkeypatch.setattr(mcp_connection, "_runtime_token_provider", lambda audience: lambda: "runtime-token")
    headers = await provider(SimpleNamespace(state=principal().state()))
    assert verify_scope(headers["X-Cymbal-Session"], SETTINGS, CALLER).store_id == "S-014"


@pytest.mark.asyncio
async def test_unsigned_factory_discovery_never_connects_or_loads_credentials(monkeypatch):
    from agents.cymbal_store_ops import mcp_connection
    values = {"CYMBAL_MCP_URL": SETTINGS.audience + "/mcp", "CYMBAL_MCP_AUDIENCE": SETTINGS.audience,
              "CYMBAL_MCP_CALLER_SERVICE_ACCOUNT": CALLER, "WORKSHOP_NAMESPACE": "demo", "STORE_OPS_ENV": "dev"}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("CYMBAL_MCP_SCOPE_KEY", raising=False)
    async def unexpected_headers(self, context):
        pytest.fail("Unsigned discovery attempted authentication/connection")
    monkeypatch.setattr(mcp_connection.RuntimeHeaderProvider, "__call__", unexpected_headers)
    toolset = make_operational_mcp_toolset()
    assert await toolset.get_tools() == []
    assert await toolset.get_tools(readonly_context=SimpleNamespace(state={})) == []
    assert await toolset.get_tools(readonly_context=SimpleNamespace(state={"user:user_id": "U-M014"})) == []


def test_every_agent_reads_store_data_only_through_mcp_when_configured(monkeypatch):
    """Deployed: no agent keeps a local store read; writes and session tools stay in the agent."""
    from agents.cymbal_store_ops import agent
    from agents.cymbal_store_ops.mcp_catalog import READS

    def names(a):
        return {getattr(tool, "name", None) or getattr(tool, "__name__", "") for tool in a.tools}

    monkeypatch.setenv("CYMBAL_MCP_URL", SETTINGS.audience + "/mcp")
    monkeypatch.setenv("CYMBAL_MCP_AUDIENCE", SETTINGS.audience)
    monkeypatch.setenv("CYMBAL_MCP_CALLER_SERVICE_ACCOUNT", CALLER)
    monkeypatch.setenv("STORE_OPS_ENV", "dev")
    filters = []
    monkeypatch.setattr(agent, "make_operational_mcp_toolset",
                        lambda tool_filter: filters.append(sorted(tool_filter)) or SimpleNamespace(name="mcp", tool_filter=tool_filter))
    root = agent.make_root_agent()
    for each in (root, *root.sub_agents):
        assert not names(each) & set(READS), each.name
    assert {"create_store_task", "delegate_task"} <= names(root.find_agent("store_tasks"))
    assert {"deliver_store_report", "identify_demo_user", "describe_store_data"} <= names(root)
    served = {name for group in filters for name in group}
    assert {"get_shift_roster", "get_shrink_signals", "query_store_data", "get_product_stock"} <= served


@pytest.mark.asyncio
async def test_actual_adk_mcp_stock_result_passes_evidence_metrics_and_errors_fail(backend):
    from google.adk.agents import LlmAgent
    from google.adk.agents.invocation_context import InvocationContext
    from google.adk.agents.readonly_context import ReadonlyContext
    from google.adk.evaluation.eval_case import IntermediateData, Invocation
    from google.adk.sessions import InMemorySessionService
    from google.adk.tools import ToolContext
    from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
    from google.genai import types

    from agents.cymbal_store_ops.mcp_connection import ScopedMcpToolset
    from eval.build_eval_set import CASES
    from eval.metrics import read_evidence_invariant, stock_invariant

    service = create_app(SETTINGS, verifier=caller_verifier)

    def http_factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(transport=httpx.ASGITransport(service), headers=headers, timeout=timeout, auth=auth)

    toolset = ScopedMcpToolset(connection_params=StreamableHTTPConnectionParams(
        url=SETTINGS.audience + '/mcp', httpx_client_factory=http_factory), tool_filter=TOOLS,
        header_provider=make_header_provider(SETTINGS, CALLER, lambda: 'verified-test-token'))
    sessions = InMemorySessionService()
    session = await sessions.create_session(app_name='mcp_metric', user_id='manager', state=principal().state())
    inv = InvocationContext(invocation_id='actual-mcp-read', agent=LlmAgent(name='test', model='unused'),
                            session=session, session_service=sessions)
    async with service.router.lifespan_context(service):
        try:
            tools = await toolset.get_tools(readonly_context=ReadonlyContext(inv))
            tool = next(t for t in tools if t.name.endswith('get_product_stock'))
            raw = await tool.run_async(args={'product_id': 'P-0101'}, tool_context=ToolContext(inv))
        finally:
            await toolset.close()
    call = types.FunctionCall(id='mcp-call', name=tool.name, args={'product_id': 'P-0101'})
    response = types.FunctionResponse(id=call.id, name=call.name, response=raw)
    actual = Invocation(user_content=CASES['osa_explanation'].conversation[0].user_content,
        final_response=types.Content(parts=[types.Part(text='7 units on hand')]),
        intermediate_data=IntermediateData(tool_uses=[call], tool_responses=[response]))
    expected = CASES['osa_explanation'].conversation
    assert read_evidence_invariant(None, [actual], expected).overall_score == 1, (tool.name, raw)
    assert stock_invariant(None, [actual], expected).overall_score == 1
    mcp_error = {'status': 'ERROR', 'error_details': 'The MCP server returned an error.', 'source': 'mcp'}
    for bad in (mcp_error, {'content': [{'type': 'text', 'text': 'not structured evidence'}]}):
        actual.intermediate_data.tool_responses = [types.FunctionResponse(id=call.id, name=call.name, response=bad)]
        assert read_evidence_invariant(None, [actual], expected).overall_score == 0
        assert stock_invariant(None, [actual], expected).overall_score == 0


@pytest.mark.asyncio
async def test_agent_gets_the_plain_result_dict_not_the_mcp_envelope(backend):
    """The briefing readers, the metrics and the model read `rows` from the result, as from a local call."""
    from google.adk.agents import LlmAgent
    from google.adk.agents.invocation_context import InvocationContext
    from google.adk.sessions import InMemorySessionService
    from google.adk.tools import ToolContext
    from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

    from agents.cymbal_store_ops.mcp_connection import ScopedMcpToolset

    app = create_app(SETTINGS, verifier=caller_verifier)

    def http_factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app), headers=headers, timeout=timeout, auth=auth)

    toolset = ScopedMcpToolset(connection_params=StreamableHTTPConnectionParams(
        url=SETTINGS.audience + "/mcp", httpx_client_factory=http_factory), tool_filter=["get_osa_exceptions"],
        header_provider=make_header_provider(SETTINGS, CALLER, lambda: "verified-test-token"))
    sessions = InMemorySessionService()
    session = await sessions.create_session(app_name="plain", user_id="U-M014", state=principal().state())
    inv = InvocationContext(invocation_id="plain", agent=LlmAgent(name="plain", model="unused"), session=session,
                            session_service=sessions)
    async with app.router.lifespan_context(app):
        try:
            tools = await toolset.get_tools(readonly_context=ToolContext(inv))
            got = await tools[0].run_async(args={"limit": 3}, tool_context=ToolContext(inv))
        finally:
            await toolset.close()
    assert got["status"] == "SUCCESS" and got["rows"], got
    assert "content" not in got
