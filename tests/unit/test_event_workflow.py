from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agents.cymbal_store_ops.events import api, source, workflow
from agents.cymbal_store_ops.events.store import EventStore
from services.store_events import worker

OWNER = "browser-test-manager"
STATE = {
    "user:user_id": "U-M014",
    "user:store_id": "S-014",
    "user:role": "store_manager",
    "_frontend_owner": OWNER,
    "_frontend_persona": "manager",
}


class Store:
    def __init__(self, job):
        self.job = job

    def claim(self, job_id, lease):
        if self.job["status"] in {"completed", "failed"}:
            return "finished", self.job
        if self.job["status"] == "processing":
            return "busy", self.job
        self.job.update(status="processing", lease=lease)
        return "claimed", dict(self.job)

    def update_claim(self, job_id, lease, values):
        if self.job.get("lease") != lease or self.job["status"] != "processing":
            return False
        self.job.update(values)
        return True


@pytest.mark.asyncio
async def test_queue_scope_rejects_unowned_or_associate_before_side_effects(monkeypatch):
    monkeypatch.setattr(api, "event_store", lambda: pytest.fail("unauthorized database access"))
    with pytest.raises(PermissionError):
        await api.enqueue_event(OWNER, "associate", "sid", STATE, "request-0001")
    with pytest.raises(PermissionError):
        await api.enqueue_event("other", "manager", "sid", STATE, "request-0001")


@pytest.mark.asyncio
async def test_queue_publishes_only_job_id_with_idempotent_request_key(monkeypatch):
    stored, published = {}, []

    def create(job_id, job):
        stored.setdefault(job_id, job)
        return stored[job_id]

    monkeypatch.setattr(api, "event_store", lambda: SimpleNamespace(create=create))
    monkeypatch.setenv("EVENTS_PROJECT", "unit-test-project")
    monkeypatch.setenv("EVENTS_TOPIC", "cymbal-store-events-unit-dev")
    from google.cloud import pubsub_v1

    monkeypatch.setattr(
        pubsub_v1,
        "PublisherClient",
        lambda: SimpleNamespace(
            topic_path=lambda p, t: f"projects/{p}/topics/{t}",
            publish=lambda topic, payload: (
                published.append(json.loads(payload)) or SimpleNamespace(result=lambda **kw: "1")
            ),
        ),
    )
    one = await api.enqueue_event(OWNER, "manager", "sid1", STATE, "request-0001")
    two = await api.enqueue_event(OWNER, "manager", "sid1", STATE, "request-0001")
    assert one == two and len(stored) == 1
    assert all(set(item) == {"job_id"} for item in published)
    assert set(next(iter(stored.values()))["state"]) == {
        "user:user_id",
        "user:store_id",
        "user:role",
    }


def test_observation_reads_actual_scoped_pending_records(fake_backend, monkeypatch):
    monkeypatch.setattr(source, "make_backend", lambda: fake_backend)
    event = source.observed_event(STATE)
    assert event["store_id"] == "S-014" and event["source"] == "bopis_orders"
    assert event["pending_order_count"] == len(event["orders"]) == 9
    assert event["records_complete"] and sum(r["qty"] for r in event["orders"]) == 13
    assert all(r["promised_at"] for r in event["orders"])
    message = source.analysis_message(event)
    assert "not a claim that a new order" in message and event["as_of"] in message


@pytest.mark.asyncio
async def test_worker_creates_owned_guarded_conversation_and_delivers_once():
    job = {"owner": OWNER, "persona": "manager", "state": STATE, "status": "queued"}
    store = Store(job)
    event = {"store_id": "S-014", "pending_order_count": 1, "as_of": "2026-10-03T09:00:00-05:00"}
    analyzer = SimpleNamespace(
        create_session=AsyncMock(return_value="analysis-123"),
        analyze=AsyncMock(
            return_value={
                "answer": "One pickup needs attention.",
                "trace": [{"id": "span1"}],
                "next_actions": [{"label": "Review orders"}],
            }
        ),
    )
    assert (
        await workflow.process_job("job1", store, analyzer, source=lambda state: event)
        == "completed"
    )
    state = analyzer.create_session.call_args.args[1]
    message = analyzer.analyze.call_args.args[2]
    assert state["_event_initial_message_sha256"] == hashlib.sha256(message.encode()).hexdigest()
    assert state["_frontend_owner"] == OWNER and state["_frontend_persona"] == "manager"
    assert (
        job["analysis_session_id"] == "analysis-123"
        and job["answer"] == "One pickup needs attention."
    )
    assert job["trace"] and job["next_actions"]
    assert await workflow.process_job("job1", store, analyzer) == "finished"
    assert analyzer.analyze.await_count == 1


@pytest.mark.asyncio
async def test_interrupted_execution_is_not_blindly_replayed():
    store = Store(
        {"status": "queued", "execution_started": True, "analysis_session_id": "retained"}
    )
    analyzer = SimpleNamespace(create_session=AsyncMock(), analyze=AsyncMock())
    assert await workflow.process_job("job1", store, analyzer) == "failed"
    analyzer.analyze.assert_not_called()
    assert store.job["analysis_session_id"] == "retained" and "interrupted" in store.job["error"]


def test_push_oidc_checks_expected_verified_identity(monkeypatch):
    monkeypatch.setenv("EVENTS_PUSH_AUDIENCE", "https://worker.example")
    monkeypatch.setenv("EVENTS_PUSH_SA", "push@example.iam.gserviceaccount.com")
    seen = {}

    def verify(token, request, audience):
        seen.update(token=token, audience=audience)
        return {"email": "push@example.iam.gserviceaccount.com", "email_verified": True}

    monkeypatch.setattr(worker.id_token, "verify_oauth2_token", verify)
    assert worker.verify_push("Bearer signed")["email_verified"]
    assert seen == {"token": "signed", "audience": "https://worker.example"}
    monkeypatch.setattr(
        worker.id_token,
        "verify_oauth2_token",
        lambda *a, **kw: {"email": "other", "email_verified": True},
    )
    with pytest.raises(ValueError):
        worker.verify_push("Bearer signed")
    with pytest.raises(ValueError):
        worker.verify_push("")


def test_push_only_accepts_job_pointer():
    def body(payload):
        return json.dumps(
            {"message": {"data": base64.b64encode(json.dumps(payload).encode()).decode()}}
        ).encode()

    job = "a" * 64
    assert worker.decode_message(body({"job_id": job})) == job
    with pytest.raises(ValueError):
        worker.decode_message(body({"job_id": job, "store_id": "S-999"}))
    with pytest.raises(ValueError):
        worker.decode_message(body({"job_id": "../x"}))


def test_actual_firestore_lease_code_enforces_fence_and_expiry(monkeypatch):
    from google.cloud import firestore

    monkeypatch.setattr(firestore, "transactional", lambda fn: fn)
    now = datetime.now(UTC)
    data = {"status": "queued", "owner": OWNER, "persona": "manager"}
    ref = SimpleNamespace(get=lambda **kw: SimpleNamespace(to_dict=lambda: dict(data)))
    transaction = SimpleNamespace(update=lambda r, values: data.update(values))
    store = object.__new__(EventStore)
    store.jobs = SimpleNamespace(document=lambda job_id: ref)
    store.client = SimpleNamespace(transaction=lambda: transaction)
    assert store.claim("j", "lease1", now=now)[0] == "claimed"
    assert store.claim("j", "lease2", now=now)[0] == "busy"
    assert not store.update_claim("j", "wrong", {"status": "completed"})
    assert store.claim("j", "lease2", now=now + timedelta(minutes=7))[0] == "claimed"
    assert not store.update_claim("j", "lease1", {"status": "completed"})
    assert store.update_claim("j", "lease2", {"status": "completed"})
    assert store.claim("j", "lease3", now=now + timedelta(minutes=8))[0] == "finished"
    assert not store.mark_read("j", "other", "manager")
    assert store.mark_read("j", OWNER, "manager")


@pytest.mark.asyncio
async def test_analyzer_reuses_single_answer_transport_and_preserves_real_activity(monkeypatch):
    from deployment import streaming

    async def events(**kwargs):
        yield {
            "id": "e1",
            "author": "store_manager_agent",
            "content": {"parts": [{"text": "Checking."}]},
        }
        yield {
            "id": "e2",
            "author": "store_manager_agent",
            "content": {
                "parts": [{"function_call": {"id": "c1", "name": "get_bopis_demand", "args": {}}}]
            },
        }
        yield {
            "id": "e3",
            "author": "store_manager_agent",
            "actions": {
                "state_delta": {
                    "ui:trace:store_manager_agent": {
                        "invocation_id": "inv1",
                        "spans": [
                            {
                                "id": "s1",
                                "kind": "tool",
                                "name": "get_bopis_demand",
                                "duration_ms": 18,
                                "status": "ok",
                            }
                        ],
                    },
                    "ui:next_actions": [
                        {"label": "Review pickup orders", "prompt": "Which pickup is due first?"}
                    ],
                }
            },
            "content": {
                "parts": [
                    {"text": "Private reasoning", "thought": True},
                    {"text": "Three orders are due before ten."},
                ]
            },
        }

    monkeypatch.setattr(streaming, "stream_query", events)
    analyzer = object.__new__(workflow.RemoteAnalyzer)
    analyzer.name = "resource"
    result = await analyzer.analyze(OWNER, "analysis-1", "Observe pickups")
    assert result["answer"] == "Three orders are due before ten."
    assert result["trace"][0]["name"] == "get_bopis_demand"
    assert result["next_actions"][0]["label"] == "Review pickup orders"
    assert "Private reasoning" not in json.dumps(result)


@pytest.mark.asyncio
async def test_analysis_source_failure_is_visible_and_never_calls_model():
    store = Store({"owner": OWNER, "persona": "manager", "state": STATE, "status": "queued"})
    analyzer = SimpleNamespace(create_session=AsyncMock(), analyze=AsyncMock())

    def broken(state):
        raise RuntimeError("Pickup read unavailable")

    assert await workflow.process_job("job1", store, analyzer, source=broken) == "failed"
    analyzer.analyze.assert_not_called()
    assert "Pickup read unavailable" in store.job["error"]
