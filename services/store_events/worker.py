from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
from functools import lru_cache

from fastapi import FastAPI, HTTPException, Request, Response
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token

from agents.cymbal_store_ops.events.api import event_store, required
from agents.cymbal_store_ops.events.workflow import RemoteAnalyzer, process_job

app = FastAPI(title="Cymbal store event worker")


def verify_push(authorization: str) -> dict:
    scheme, _, token = authorization.partition(" ")
    if scheme != "Bearer" or not token:
        raise ValueError("A Pub/Sub OIDC bearer token is required")
    claims = id_token.verify_oauth2_token(
        token, GoogleRequest(), audience=required("EVENTS_PUSH_AUDIENCE")
    )
    if (
        claims.get("email") != required("EVENTS_PUSH_SA")
        or claims.get("email_verified") is not True
    ):
        raise ValueError("Unexpected Pub/Sub push identity")
    return claims


def decode_message(body: bytes) -> str:
    if len(body) > 8192:
        raise ValueError("Push message exceeds the size limit")
    envelope = json.loads(body)
    if not isinstance(envelope, dict) or not isinstance(envelope.get("message"), dict):
        raise ValueError("Invalid Pub/Sub envelope")
    encoded = envelope.get("message", {}).get("data", "")
    payload = json.loads(base64.b64decode(encoded, validate=True))
    if (
        not isinstance(payload, dict)
        or set(payload) != {"job_id"}
        or not re.fullmatch(r"[a-f0-9]{64}", str(payload["job_id"]))
    ):
        raise ValueError("Pub/Sub payload must contain only a valid job_id")
    return payload["job_id"]


@lru_cache(maxsize=1)
def analyzer() -> RemoteAnalyzer:
    return RemoteAnalyzer(required("EVENTS_ENGINE"))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/push")
async def push(request: Request):
    try:
        await asyncio.to_thread(verify_push, request.headers.get("authorization", ""))
    except (ValueError, KeyError) as exc:
        raise HTTPException(401, "Invalid Pub/Sub push identity") from exc
    try:
        job_id = decode_message(await request.body())
    except (ValueError, TypeError, KeyError, binascii.Error) as exc:
        raise HTTPException(400, "Invalid Pub/Sub event payload") from exc
    status = await process_job(job_id, event_store(), analyzer())
    if status in {"busy", "lease_lost"}:
        raise HTTPException(503, "Event analysis is already leased")
    return Response(status_code=204)
