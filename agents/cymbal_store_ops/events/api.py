"""Trusted frontend integration. Call only after authenticating and owning the origin session."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from functools import lru_cache

from agents.cymbal_store_ops.events.store import EventStore

REQUEST_ID = re.compile(r"^[a-zA-Z0-9_-]{8,80}$")


def required(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        raise RuntimeError(f"{key} must be configured for store events")
    return value


@lru_cache(maxsize=1)
def event_store() -> EventStore:
    return EventStore(
        required("EVENTS_PROJECT"),
        required("EVENTS_DATABASE"),
        os.environ.get("EVENTS_COLLECTION", "event_jobs"),
    )


async def enqueue_event(
    owner: str, persona: str, origin_session_id: str, trusted_state: dict, request_id: str
) -> dict:
    """Enqueue one observed pickup event. No message, identity or store may come from request JSON."""
    if persona != "manager" or trusted_state.get("user:role") != "store_manager":
        raise PermissionError("Store managers can request event analysis")
    if (
        not owner
        or trusted_state.get("_frontend_owner") != owner
        or trusted_state.get("_frontend_persona") != persona
    ):
        raise PermissionError("Event origin must be an owned manager conversation")
    if not origin_session_id or not REQUEST_ID.fullmatch(request_id):
        raise ValueError("An origin session and stable request ID are required")
    state = {
        k: trusted_state[k]
        for k in ("user:user_id", "user:store_id", "user:role", "user:first_name")
        if k in trusted_state
    }
    if not state.get("user:user_id") or not state.get("user:store_id"):
        raise ValueError("Signed store identity is required")
    job_id = hashlib.sha256(
        json.dumps([owner, persona, origin_session_id, request_id]).encode()
    ).hexdigest()
    now = datetime.now(UTC)
    job = {
        "owner": owner,
        "persona": persona,
        "origin_session_id": origin_session_id,
        "state": state,
        "event_type": "pickup_deadline",
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "attempts": 0,
        "read_at": None,
        "title": "Pickup priorities",
    }
    existing = await asyncio.to_thread(event_store().create, job_id, job)
    if existing["status"] == "queued":
        from google.cloud import pubsub_v1

        publisher = pubsub_v1.PublisherClient()
        topic = publisher.topic_path(required("EVENTS_PROJECT"), required("EVENTS_TOPIC"))
        await asyncio.to_thread(
            lambda: publisher.publish(topic, json.dumps({"job_id": job_id}).encode()).result(
                timeout=20
            )
        )
    return {"job_id": job_id, "status": existing["status"]}


async def list_notifications(owner: str, persona: str) -> dict:
    rows = await asyncio.to_thread(event_store().list_owned, owner, persona)
    return {
        "notifications": [
            {
                k: row.get(k)
                for k in (
                    "job_id",
                    "title",
                    "status",
                    "created_at",
                    "updated_at",
                    "read_at",
                    "analysis_session_id",
                    "error",
                )
            }
            | {"summary": row.get("answer", "")[:600]}
            for row in rows
        ]
    }


async def mark_read(owner: str, persona: str, job_id: str) -> bool:
    if not re.fullmatch(r"[a-f0-9]{64}", job_id):
        return False
    return await asyncio.to_thread(event_store().mark_read, job_id, owner, persona)
