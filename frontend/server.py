"""Lightweight standalone chat frontend for the Cymbal Beauty store operations agents.

    uv run python frontend/server.py --target local                 # in-process ADK runner (dev loop)
    uv run python frontend/server.py --target agent-engine --env dev  # deployed Agent Runtime (formerly Agent Engine)

Open http://localhost:8080. One HTML page, server-sent events, no build step. The server holds the
credentials (ADC); the browser only ever talks to this server. Tool calls, transfers, state deltas
and human-confirmation requests are streamed as typed events so the UI can show what the agent did.
No fallbacks: a bad target, a missing engine id, or a failed query surfaces as an error event.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from google.adk.events import Event
from google.adk.sessions import Session
from pydantic import BaseModel

from agents.cymbal_store_ops import fixtures as F
from frontend.session_access import as_dict, ensure_browser, public_state, runtime_user

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
SCENARIOS = HERE / "scenarios.yaml"

app = FastAPI(title="Cymbal Beauty store operations frontend")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
TARGET: dict[str, Any] = {"kind": "local"}

# Set by the deploy; unset locally, and then the app is open because it is on your laptop.
PASSWORD = os.environ.get("FRONTEND_PASSWORD", "").strip()
COOKIE = "cymbal_frontend"


def _token() -> str:
    """What a signed-in browser holds. It is derived from the password, so rotating the secret signs everyone out."""
    return hashlib.sha256(f"cymbal-frontend:{PASSWORD}".encode()).hexdigest()


def require_sign_in(request: Request) -> None:
    if PASSWORD and not hmac.compare_digest(request.cookies.get(COOKIE, ""), _token()):
        raise HTTPException(status_code=401, detail="sign in first")


# --------------------------------------------------------------------------- backends
class LocalTarget:
    """In-process ADK Runner over the same App that ships to Agent Runtime."""

    def __init__(self) -> None:
        from google.adk.runners import InMemoryRunner

        from agents.cymbal_store_ops.agent import app as adk_app
        self.app_name = adk_app.name
        self.runner = InMemoryRunner(app=adk_app)

    async def create_session(self, user_id: str, state: dict) -> str:
        s = await self.runner.session_service.create_session(app_name=self.app_name, user_id=user_id, state=state)
        return s.id

    async def get_session(self, user_id: str, session_id: str):
        return as_dict(await self.runner.session_service.get_session(
            app_name=self.app_name, user_id=user_id, session_id=session_id))

    async def list_sessions(self, user_id: str):
        result = await self.runner.session_service.list_sessions(app_name=self.app_name, user_id=user_id)
        return [as_dict(s) for s in result.sessions]

    async def stream(self, user_id: str, session_id: str, message: Any, invocation_id: str | None) -> AsyncIterator[dict]:
        async for ev in self.runner.run_async(user_id=user_id, session_id=session_id, new_message=message,
                                              invocation_id=invocation_id):
            yield ev.model_dump(mode="json", exclude_none=True)


class AgentEngineTarget:
    """Deployed agent: queries go to the engine labelled with this namespace and environment.

    Nothing here is given a resource name. The service knows its namespace and environment, and asks Agent
    Runtime which engine carries those labels, so whoever deploys this finds their own agent and a redeploy of
    that agent (a new revision on the same engine) needs no change here.

    The lookup is lazy on purpose. Deploying this app before the agent it talks to is a normal order to do a lab
    in, and resolving at startup would turn that into a crash-looping revision with the reason buried in the logs.
    Instead the service starts, says what is wrong on /api/config, and picks the engine up on the next request
    once it exists."""

    def __init__(self, env: str) -> None:
        self.env = env
        self._remote = None
        self._name = ""
        self._error = ""
        self.resolve()

    def resolve(self) -> bool:
        """Find the engine, or record why not. True when this target can answer."""
        if self._remote is not None:
            return True
        from deployment._common import client_for, load_config, resolve_engine_name

        try:
            cfg = load_config(self.env)
            client = client_for(cfg)
            name = resolve_engine_name(cfg, client)
            self._remote = client.agent_engines.get(name=name)
            self._name, self._error = name, ""
            return True
        except Exception as e:  # noqa: BLE001 — reported to the page, never swallowed
            self._error = f"{type(e).__name__}: {e}"
            return False

    @property
    def name(self) -> str:
        return self._name or f"no engine yet — {self._error}"

    @property
    def remote(self):
        if not self.resolve():
            raise HTTPException(status_code=503, detail=(
                f"This app has no agent to talk to yet. It looks for the engine labelled ns={os.environ.get('WORKSHOP_NAMESPACE', '?')} "
                f"env={self.env}. Deploy it with `uv run python deployment/release.py && uv run python deployment/deploy.py --env {self.env} --release release.json`, then ask again — nothing here needs "
                f"redeploying.\nThe lookup said: {self._error}"))
        return self._remote

    async def create_session(self, user_id: str, state: dict) -> str:
        s = await self.remote.async_create_session(user_id=user_id, state=state)
        return s["id"] if isinstance(s, dict) else s.id

    async def get_session(self, user_id: str, session_id: str):
        from google.api_core.exceptions import NotFound
        from google.genai.errors import ClientError
        try:
            value = await self.remote.async_get_session(user_id=user_id, session_id=session_id)
            return Session.model_validate(as_dict(value)).model_dump(mode="json", exclude_none=True) if value is not None else None
        except NotFound:
            return None
        except ClientError as exc:
            # The pinned runtime wraps its session ownership rejection as INVALID_ARGUMENT.
            # Match the exact scoped denial; unrelated engine/configuration failures must surface.
            denial = f"Session {session_id} does not belong to user {user_id}."
            if exc.code == 404 or (exc.code == 400 and denial in str(exc)):
                return None
            raise

    async def list_sessions(self, user_id: str):
        result = as_dict(await self.remote.async_list_sessions(user_id=user_id))
        # Runtime REST uses lastUpdateTime/appName/userId; normalize the typed
        # envelope without renaming arbitrary state or tool-result data keys.
        return [Session.model_validate(as_dict(s)).model_dump(mode="json", exclude_none=True)
                for s in result.get("sessions", [])]

    async def stream(self, user_id: str, session_id: str, message: Any, invocation_id: str | None) -> AsyncIterator[dict]:
        from deployment.streaming import stream_query

        _ = self.remote  # Resolve the target and surface configuration errors before streaming.
        async for ev in stream_query(name=self._name, user_id=user_id, session_id=session_id,
                                     message=message, invocation_id=invocation_id):
            yield ev


def _target():
    return TARGET["impl"]


# --------------------------------------------------------------------------- event shaping
def trace_payload(value: Any, depth: int = 0) -> Any:
    """Keep bounded execution data; never forward model thought parts."""
    if depth > 8:
        return "[nested data omitted]"
    if isinstance(value, str):
        return value if len(value) <= 12000 else value[:12000] + "… [truncated]"
    if isinstance(value, list):
        return [trace_payload(v, depth + 1) for v in value[:80]
                if not (isinstance(v, dict) and v.get("thought") is True)]
    if isinstance(value, dict):
        if value.get("thought") is True:
            return "[thought content omitted]"
        return {k: trace_payload(v, depth + 1) for k, v in list(value.items())[:80]
                if k not in {"thought", "thoughts", "thought_signature", "thoughtSignature", "reasoning"}}
    return value


def shape_trace(key: str, value: Any) -> dict | None:
    """Support per-agent trace snapshots, including nested AgentTool invocations."""
    spans = value.get("spans") if isinstance(value, dict) else value
    if not isinstance(spans, list):
        return None
    fields = {"id", "parent_id", "invocation_id", "root_invocation_id", "agent", "name", "kind", "start_ms", "duration_ms", "status", "input", "output"}
    clean = []
    for span in spans[:300]:
        if not isinstance(span, dict) or not isinstance(span.get("id"), str) or span.get("kind") not in {"agent", "tool", "model"}:
            continue
        clean.append({k: trace_payload(v) for k, v in span.items() if k in fields})
    return {"type": "trace", "source": key, "invocation_id": value.get("invocation_id") if isinstance(value, dict) else None,
            "root_invocation_id": value.get("root_invocation_id") if isinstance(value, dict) else None, "spans": clean}


def shape(ev: dict) -> list[dict]:
    """Turn one ADK event (as dict) into typed UI events."""
    out: list[dict] = []
    author = ev.get("author", "")
    actions = ev.get("actions") or {}
    if actions.get("transfer_to_agent"):
        out.append({"type": "transfer", "from": author, "to": actions["transfer_to_agent"]})
    for filename, version in (actions.get("artifact_delta") or {}).items():
        if isinstance(filename, str) and isinstance(version, int):
            out.append({"type": "artifact", "filename": filename, "version": version})
    lr = set(ev.get("long_running_tool_ids") or [])
    text_parts = []
    for part in (ev.get("content") or {}).get("parts") or []:
        if part.get("thought"):
            continue
        fc = part.get("function_call")
        fr = part.get("function_response")
        if fc:
            if fc.get("name") == "adk_request_confirmation" and fc.get("id") in lr:
                orig = (fc.get("args") or {}).get("originalFunctionCall", {})
                out.append({"type": "confirmation", "fc_id": fc["id"], "invocation_id": ev.get("invocation_id"),
                            "tool": orig.get("name"), "args": orig.get("args"),
                            "hint": (fc.get("args") or {}).get("toolConfirmation", {}).get("hint", "")})
            else:
                out.append({"type": "tool_call", "author": author, "name": fc.get("name"), "args": fc.get("args"), "call_id": fc.get("id")})
        elif fr:
            resp = fr.get("response") or {}
            # The whole response, not a preview: the UI renders tables and cards from what the tools already
            # return, which is what keeps the rich display out of the agent. `preview` stays for the raw view.
            out.append({"type": "tool_result", "author": author, "name": fr.get("name"),
                        "call_id": fr.get("id"), "status": resp.get("status") or ("error" if "error" in resp else "ok"),
                        "data": resp, "preview": json.dumps(resp, default=str)[:400]})
        elif part.get("text"):
            text_parts.append(part["text"])
    if text_parts:
        kind = "text" if author in {"store_manager_agent", "associate_development"} else "agent_note"
        out.append({"type": kind, "author": author, "text": "\n".join(text_parts),
                    "partial": bool(ev.get("partial")), "event_id": ev.get("id")})
    delta = {}
    for key, value in (actions.get("state_delta") or {}).items():
        if key.startswith("ui:trace:"):
            trace = shape_trace(key, value)
            if trace:
                out.append(trace)
        elif not key.startswith("_"):
            delta[key] = value
    if delta:
        out.append({"type": "state", "delta": delta})
    return out


async def sse(gen: AsyncIterator[dict]) -> AsyncIterator[bytes]:
    """Stream activity immediately, then publish one completed conversational answer.

    A consultant's node events and the coordinator's final answer share a stream.
    Text before a subsequent tool call or handoff is a working note, not another
    answer. Buffer only that candidate text, never confirmations or tool activity.
    """
    reply = None
    task_reply = None
    confirmation = False
    failed = False
    seen = set()

    def frame(item: dict) -> bytes:
        return f"data: {json.dumps(item, default=str)}\n\n".encode()

    try:
        async for ev in gen:
            # Streaming chunks and their final aggregate may share an ID. Only
            # identical deliveries are duplicates; retain a changed aggregate.
            if ev.get("id"):
                key = (ev["id"], json.dumps(ev, sort_keys=True, default=str))
                if key in seen:
                    continue
                seen.add(key)
            items = shape(ev)
            if ev.get("error_message"):
                for item in items:
                    if item["type"] == "trace":
                        yield frame(item)
                raise RuntimeError(ev["error_message"])
            working = any(i["type"] in {"tool_call", "transfer", "confirmation"} for i in items)
            if working and reply:
                yield frame({**reply, "type": "agent_note"})
                reply = None
            for item in items:
                kind = item["type"]
                confirmation |= kind == "confirmation"
                if kind in {"text", "agent_note"}:
                    if item.get("partial"):
                        continue
                    public = kind == "text" or (item.get("author") == "store_tasks" and not confirmation)
                    if item.get("author") == "store_tasks" and not working and not confirmation:
                        task_reply = item
                    if public and not working:
                        if reply:
                            yield frame({**reply, "type": "agent_note"})
                        reply = item
                        continue
                    item = {**item, "type": "agent_note"}
                yield frame(item)
    except Exception as e:  # noqa: BLE001 — surfaced to the UI, never swallowed
        failed = True
        yield frame({'type': 'error', 'message': f'{type(e).__name__}: {e}'})
    if not reply and not confirmation:
        reply = task_reply
    if reply and not failed:
        yield frame({**reply, 'type': 'text'})
    yield b"data: {\"type\": \"done\"}\n\n"


# --------------------------------------------------------------------------- API
DEMO_IDENTITIES = {
    # Seeded into session state the way an authenticated app would after device sign-in; never taken from chat.
    "manager": {"user:user_id": F.HERO_MANAGER_ID, "user:store_id": F.HERO_STORE_ID,
                "user:role": "store_manager", "user:first_name": F.HERO_MANAGER_FIRST_NAME},
    "associate": {"user:user_id": F.HERO_ASSOCIATE_ID, "user:store_id": F.HERO_STORE_ID,
                  "user:role": "associate", "user:first_name": F.HERO_ASSOCIATE_FIRST_NAME},
}


class NewSession(BaseModel):
    title: str = "Store conversation"
    user_id: str = "guest"
    demo_identity: str | None = None   # "manager" | "associate" — which demo sign-in to seed (see DEMO_IDENTITIES)


class Chat(BaseModel):
    user_id: str = "guest"
    persona: str = "manager"
    session_id: str
    text: str


class Login(BaseModel):
    password: str = ""


class Confirm(BaseModel):
    user_id: str = "guest"
    persona: str = "manager"
    session_id: str
    invocation_id: str
    fc_id: str
    confirmed: bool


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/config")
async def config(request: Request):
    """What the page needs before it can do anything: whether a password is in force, and whether this browser has it."""
    signed_in = not PASSWORD or hmac.compare_digest(request.cookies.get(COOKIE, ""), _token())
    response = JSONResponse({"password_required": bool(PASSWORD), "signed_in": signed_in,
            "target": {"kind": TARGET["kind"], "name": getattr(TARGET.get("impl"), "name", "local")},
            "capabilities": {"notifications": all(os.environ.get(k) for k in
                ("EVENTS_PROJECT", "EVENTS_DATABASE", "EVENTS_TOPIC"))}})
    if signed_in:
        ensure_browser(request, response, PASSWORD, secure=bool(os.environ.get("PORT")))
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/login")
async def login(request: Request, body: Login):
    if PASSWORD and not hmac.compare_digest(body.password.strip(), PASSWORD):
        raise HTTPException(status_code=401, detail="that is not the password for this deployment")
    r = JSONResponse({"ok": True})
    ensure_browser(request, r, PASSWORD, secure=bool(os.environ.get("PORT")))
    r.set_cookie(COOKIE, _token(), httponly=True, samesite="lax", max_age=12 * 3600,
                 secure=bool(os.environ.get("PORT")))   # a container host means it is served over TLS
    return r


@app.get("/api/scenarios")
async def scenarios(request: Request):
    """Persona-scoped starter pools; journey links and validation status describe each prompt's coverage."""
    require_sign_in(request)
    import yaml
    if not SCENARIOS.is_file():
        raise HTTPException(status_code=500, detail=f"{SCENARIOS} is missing: the app ships its scenarios with it")
    return yaml.safe_load(SCENARIOS.read_text())


@app.get("/api/target")
async def target():
    return {"kind": TARGET["kind"], "name": getattr(TARGET.get("impl"), "name", "local")}


@app.post("/api/sessions")
async def new_session(request: Request, body: NewSession):
    require_sign_in(request)
    if body.demo_identity and body.demo_identity not in DEMO_IDENTITIES:
        raise HTTPException(status_code=400, detail=f"unknown demo identity {body.demo_identity!r}; use one of {sorted(DEMO_IDENTITIES)}")
    persona = body.demo_identity or "manager"
    user_id = runtime_user(request, PASSWORD, persona)
    state = dict(DEMO_IDENTITIES[persona])
    state.update({"_frontend_owner": user_id, "_frontend_persona": persona,
                  "ui:conversation_title": body.title.strip()[:90] or "Store conversation"})
    sid = await _target().create_session(user_id, state)
    return {"session_id": sid, "state": public_state(state)}


async def owned_session(request: Request, session_id: str, persona: str):
    require_sign_in(request)
    user_id = runtime_user(request, PASSWORD, persona)
    session = await _target().get_session(user_id, session_id)
    if not session or session.get("state", {}).get("_frontend_owner") != user_id:
        raise HTTPException(404, "Conversation not found.")
    if session["state"].get("_frontend_persona") != persona:
        raise HTTPException(404, "Conversation not found.")
    return user_id, session


class TriggerEvent(BaseModel):
    session_id: str
    persona: str = "manager"
    request_id: str


@app.post("/api/events", status_code=202)
async def trigger_event(request: Request, body: TriggerEvent):
    from agents.cymbal_store_ops.events.api import enqueue_event

    owner, session = await owned_session(request, body.session_id, body.persona)
    try:
        return await enqueue_event(owner, body.persona, body.session_id, session["state"], body.request_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/notifications")
async def notifications(request: Request, persona: str = "manager"):
    from agents.cymbal_store_ops.events.api import list_notifications

    require_sign_in(request)
    return await list_notifications(runtime_user(request, PASSWORD, persona), persona)


@app.post("/api/notifications/{job_id}/read")
async def notification_read(request: Request, job_id: str, persona: str = "manager"):
    from agents.cymbal_store_ops.events.api import mark_read

    require_sign_in(request)
    if not await mark_read(runtime_user(request, PASSWORD, persona), persona, job_id):
        raise HTTPException(404, "Notification not found.")
    return {"ok": True}


@app.get("/api/sessions")
async def list_sessions(request: Request, persona: str = "manager"):
    require_sign_in(request)
    user_id = runtime_user(request, PASSWORD, persona)
    sessions = await _target().list_sessions(user_id)
    result = []
    for session in sessions:
        state = session.get("state") or {}
        if state.get("_frontend_owner") != user_id or state.get("_frontend_persona") != persona:
            continue
        result.append({"session_id": session["id"], "last_update_time": session.get("last_update_time", 0),
                       "title": state.get("ui:conversation_title", "Store conversation")})
    return {"sessions": sorted(result, key=lambda s: s["last_update_time"], reverse=True)[:50]}


@app.get("/api/sessions/{session_id}")
async def session_history(request: Request, session_id: str, persona: str = "manager"):
    _, session = await owned_session(request, session_id, persona)
    history, group = [], []

    async def flush():
        async def source():
            for event in group:
                yield event
        async for frame in sse(source()):
            item = json.loads(frame.decode().removeprefix("data: "))
            if item["type"] == "done":
                continue
            # A historical approval request is not a live approval control.
            if item["type"] == "confirmation":
                item = {"type": "agent_note", "author": "store_tasks", "text": "Task approval requested."}
            history.append(item)
        group.clear()

    for event in session.get("events") or []:
        # Runtime session REST responses use camelCase aliases; local ADK sessions
        # use snake_case. Normalize the event envelope through ADK while leaving
        # arbitrary tool-result and state payload keys unchanged.
        event = Event.model_validate(as_dict(event)).model_dump(mode="json", exclude_none=True)
        if event.get("author") == "user":
            await flush()
            text = "\n".join(p["text"] for p in (event.get("content") or {}).get("parts", [])
                             if p.get("text") and not p.get("thought"))
            if text:
                event_hash = session.get("state", {}).get("_event_initial_message_sha256")
                if event_hash and hashlib.sha256(text.encode()).hexdigest() == event_hash:
                    history.append({"type": "observation", "text": "Review recorded pickup deadlines."})
                else:
                    history.append({"type": "user", "text": text})
        else:
            group.append(event)
    await flush()
    return {"session_id": session_id, "state": public_state(session.get("state", {})), "events": history}


def artifact_service():
    if TARGET["kind"] == "local":
        return _target().runner.artifact_service
    from agents.cymbal_store_ops.artifact_storage import create_artifact_service
    return create_artifact_service()


def safe_pdf_name(filename: str) -> bool:
    import re
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,149}\.pdf", filename))


async def artifact_scope(request: Request, session_id: str, persona: str):
    user_id, session = await owned_session(request, session_id, persona)
    if session["state"].get("user:role") != "store_manager":
        raise HTTPException(403, "Store reports are available to managers.")
    return user_id, session


@app.get("/api/sessions/{session_id}/artifacts")
async def list_artifacts(request: Request, session_id: str, persona: str = "manager"):
    user_id, _ = await artifact_scope(request, session_id, persona)
    service = artifact_service()
    keys = await service.list_artifact_keys(app_name="cymbal_store_ops", user_id=user_id, session_id=session_id)
    result = []
    for filename in keys:
        if not safe_pdf_name(filename):
            continue
        versions = await service.list_versions(app_name="cymbal_store_ops", user_id=user_id,
                                               session_id=session_id, filename=filename)
        if versions:
            result.append({"filename": filename, "version": max(versions), "mime_type": "application/pdf"})
    return {"artifacts": result}


@app.get("/api/sessions/{session_id}/artifacts/{filename}")
async def download_artifact(request: Request, session_id: str, filename: str, version: int,
                            persona: str = "manager", download: bool = False):
    if not safe_pdf_name(filename) or version < 0:
        raise HTTPException(400, "Invalid report name or version.")
    user_id, session = await artifact_scope(request, session_id, persona)
    service = artifact_service()
    scope = dict(app_name="cymbal_store_ops", user_id=user_id, session_id=session_id,
                 filename=filename, version=version)
    metadata = await service.get_artifact_version(**scope)
    if metadata is None or metadata.custom_metadata.get("store_id") != session["state"].get("user:store_id"):
        raise HTTPException(404, "Report not found.")
    part = await service.load_artifact(**scope)
    data = part.inline_data if part else None
    if not data or data.mime_type != "application/pdf" or not data.data.startswith(b"%PDF-"):
        raise HTTPException(422, "The report is not a valid PDF.")
    if len(data.data) > 5 * 1024 * 1024:
        raise HTTPException(413, "Report exceeds the download size limit.")
    return Response(data.data, media_type="application/pdf", headers={
        "Content-Disposition": f'{"attachment" if download else "inline"}; filename="{filename}"',
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "frame-ancestors 'self'", "X-Frame-Options": "SAMEORIGIN"})


@app.post("/api/chat")
async def chat(request: Request, body: Chat):
    require_sign_in(request)
    if not body.text.strip():
        raise HTTPException(400, "empty message")
    user_id, _ = await owned_session(request, body.session_id, body.persona)
    from google.genai import types
    message = types.Content(role="user", parts=[types.Part(text=body.text)]) if TARGET["kind"] == "local" else body.text
    return StreamingResponse(sse(_target().stream(user_id, body.session_id, message, None)), media_type="text/event-stream")


@app.post("/api/confirm")
async def confirm(request: Request, body: Confirm):
    require_sign_in(request)
    user_id, _ = await owned_session(request, body.session_id, body.persona)
    from google.genai import types
    part = types.Part(function_response=types.FunctionResponse(id=body.fc_id, name="adk_request_confirmation",
                                                               response={"confirmed": body.confirmed}))
    if TARGET["kind"] == "local":
        message: Any = types.Content(role="user", parts=[part])
    else:
        message = {"role": "user", "parts": [part.model_dump(mode="json", exclude_none=True)]}
    return StreamingResponse(sse(_target().stream(user_id, body.session_id, message, body.invocation_id)),
                             media_type="text/event-stream")


def build_parser() -> argparse.ArgumentParser:
    """The CLI. A container host sets PORT and reaches the server from outside the container, so PORT being set is
    what switches the bind address from loopback to every interface; there is no separate "am I in a container" flag."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", choices=["local", "agent-engine"], default="local")
    ap.add_argument("--env", default=os.environ.get("STORE_OPS_ENV", "dev"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")),
                    help="default: $PORT when set (Cloud Run sets it), else 8080")
    ap.add_argument("--host", default="0.0.0.0" if os.environ.get("PORT") else "127.0.0.1",  # noqa: S104
                    help="default: 127.0.0.1 locally, 0.0.0.0 when $PORT is set")
    return ap


def main() -> int:
    a = build_parser().parse_args()
    TARGET["kind"] = a.target
    TARGET["impl"] = LocalTarget() if a.target == "local" else AgentEngineTarget(a.env)
    if a.target == "local":
        # The BigQuery client, the dataset lookup and the first query happen here, not inside the first answer.
        from agents.cymbal_store_ops.tools.data_backend import prewarm
        print("warming the data backend…", flush=True)
        prewarm()
    import uvicorn
    where = f"http://localhost:{a.port}" if a.host == "127.0.0.1" else f"{a.host}:{a.port}"
    print(f"frontend: target={a.target} ({getattr(TARGET['impl'], 'name', 'in-process runner')}) -> {where}")
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
