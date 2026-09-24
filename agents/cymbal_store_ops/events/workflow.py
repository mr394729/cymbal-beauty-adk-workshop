"""A durable event job produces one owned Agent Runtime conversation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime

from agents.cymbal_store_ops.events.source import analysis_message, observed_event


class RemoteAnalyzer:
    def __init__(self, name: str):
        import vertexai

        pieces = name.split("/")
        if (
            len(pieces) != 6
            or pieces[0] != "projects"
            or pieces[2] != "locations"
            or pieces[4] != "reasoningEngines"
        ):
            raise ValueError("EVENTS_ENGINE must be a full Agent Runtime resource")
        self.name = name
        self.remote = vertexai.Client(project=pieces[1], location=pieces[3]).agent_engines.get(
            name=name
        )

    async def create_session(self, owner: str, state: dict) -> str:
        session = await self.remote.async_create_session(user_id=owner, state=state)
        return session["id"] if isinstance(session, dict) else session.id

    async def analyze(self, owner: str, session_id: str, message: str) -> dict:
        from deployment.streaming import stream_query
        from frontend.server import sse

        result = {"answer": "", "trace": [], "next_actions": [], "trace_truncated": False}
        spans, trace_bytes = {}, 0
        # Reuse the chat transport's authoritative single-answer semantics.
        async for frame in sse(
            stream_query(name=self.name, user_id=owner, session_id=session_id, message=message)
        ):
            event = json.loads(frame.decode().removeprefix("data: ").strip())
            kind = event.get("type")
            if kind in {"error", "confirmation"}:
                raise RuntimeError(
                    event.get("message", "Event analysis requested a write confirmation")
                )
            if kind == "text":
                result["answer"] = event["text"][:20000]
            elif kind == "state" and "ui:next_actions" in event.get("delta", {}):
                value = event["delta"]["ui:next_actions"]
                result["next_actions"] = value if isinstance(value, list) else []
            elif kind == "trace":
                for span in event.get("spans", []):
                    span_id = span["id"]
                    length = len(json.dumps(span, ensure_ascii=False).encode())
                    old_length = (
                        len(json.dumps(spans[span_id], ensure_ascii=False).encode())
                        if span_id in spans
                        else 0
                    )
                    if (
                        span_id in spans or len(spans) < 100
                    ) and trace_bytes - old_length + length < 450000:
                        spans[span_id] = span
                        trace_bytes += length - old_length
                    else:
                        result["trace_truncated"] = True
        if not result["answer"]:
            raise RuntimeError("Event analysis returned no completed answer")
        result["trace"] = list(spans.values())
        return result


async def process_job(job_id: str, store, analyzer, *, source=observed_event) -> str:
    lease = uuid.uuid4().hex
    status, job = await asyncio.to_thread(store.claim, job_id, lease)
    if status != "claimed":
        return status
    try:
        if job.get("execution_started"):
            raise RuntimeError(
                "Previous analysis was interrupted; its conversation is retained. Start a new event to retry."
            )
        if (
            job.get("persona") != "manager"
            or job.get("state", {}).get("user:role") != "store_manager"
        ):
            raise PermissionError("Event job does not contain a manager scope")
        event = await asyncio.to_thread(source, job["state"])
        message = analysis_message(event)
        state = {
            **job["state"],
            "_frontend_owner": job["owner"],
            "_frontend_persona": job["persona"],
            "_event_initial_message_sha256": hashlib.sha256(message.encode()).hexdigest(),
            "ui:conversation_title": "Pickup priorities",
            "_event_job_id": job_id,
        }
        session_id = await analyzer.create_session(job["owner"], state)
        if not await asyncio.to_thread(
            store.update_claim,
            job_id,
            lease,
            {"analysis_session_id": session_id, "source_event": event, "execution_started": True},
        ):
            raise RuntimeError("Event job lease was lost before analysis")
        result = await asyncio.wait_for(
            analyzer.analyze(job["owner"], session_id, message), timeout=240
        )
        committed = await asyncio.to_thread(
            store.update_claim,
            job_id,
            lease,
            {
                **result,
                "status": "completed",
                "completed_at": datetime.now(UTC),
                "lease_until": None,
            },
        )
        return "completed" if committed else "lease_lost"
    except Exception as exc:
        await asyncio.to_thread(
            store.update_claim,
            job_id,
            lease,
            {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}"[:1200],
                "lease_until": None,
            },
        )
        return "failed"
