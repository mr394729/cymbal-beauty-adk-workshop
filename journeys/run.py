"""Run persona journeys against the store-operations agent and grade them.

A journey is one session: a persona signs in once and asks a series of questions in order, the way a
store manager, an associate, a district manager or a calling system would during a shift. Each turn
declares what must happen (tools that must run, tools that must not, phrases the answer must contain,
whether it must decline), so a run produces graded transcripts a reviewer can read.

    uv run python journeys/run.py                          # every journey, in-process runner
    uv run python journeys/run.py --journey manager-start-of-shift
    uv run python journeys/run.py --tag adversarial
    uv run python journeys/run.py --target remote --env dev  # the deployed Agent Runtime
    uv run python journeys/run.py --list

Writes build/journeys/<journey>.md (one section per turn) and build/journeys/summary.md.
Exit code 1 when any expectation failed, 2 when the runner itself could not run.

Confirmations: a turn with `approve: true` answers the tool-confirmation dialog with yes, every other
turn answers no. Journeys that write carry `writes: true` and run serially after the read-only ones;
run `bash data/load.sh --env dev --tables store_tasks` before and after a batch that includes them.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

JOURNEY_DIR = Path(__file__).resolve().parent
PERSONAS_FILE = JOURNEY_DIR / "personas.yaml"
OUT_DIR = ROOT / "build" / "journeys"
CONFIRMATION_TOOL = "adk_request_confirmation"
MAX_CONFIRMATION_ROUNDS = 4

# ---------------------------------------------------------------------------- schema
JOURNEY_KEYS = {"kind", "id", "title", "persona", "goal", "tags", "notes", "writes", "turns"}
REQUIRED_JOURNEY_KEYS = {"id", "title", "persona", "goal", "turns"}
TURN_KEYS = {"say", "expect", "approve", "note"}
EXPECT_KEYS = {"tools_all", "tools_any", "tools_none", "contains_all", "contains_any", "not_contains",
               "regex_all", "regex_none", "refusal", "no_tool_errors", "tool_error_regex",
               "confirmation", "max_latency_s", "state_has"}
LIST_EXPECT_KEYS = {"tools_all", "tools_any", "tools_none", "contains_all", "contains_any", "not_contains",
                    "regex_all", "regex_none"}
PERSONA_KEYS = {"name", "role", "associate_id", "store_id", "signed_in", "description"}
ROLES = ("associate", "store_manager", "district_manager")
CONFIRMATION_VALUES = ("required", "forbidden")
ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,49}$")

# A declining answer: the agent itself says it will not or cannot do the thing, or names the rule that stops
# it. Every alternative here is attributed — to the agent ("I can't"), to the data ("not tracked in our tools"),
# or to a policy ("this session is scoped to"). An unattributed "cannot" is not enough: four live answers used
# one descriptively ("3 pending BOPIS orders requiring 4 units that cannot currently be picked from the shelf",
# "if associates cannot pick from the backroom immediately") in the middle of a perfectly ordinary answer.
REFUSAL_RE = re.compile(
    r"\b(?:i|we)\b(?:\s+\w+){0,2}?\s+(?:can(?:no|'?)t|cannot|can not|am unable to|'?m unable to|are unable to|"
    r"do(?:n'?t| not) have|do(?:n'?t| not) track|do(?:n'?t| not) see|have no access|has no access)\b|"
    r"\bi'?m not able to\b|\bnot something i can\b|\bisn'?t something i can\b|\bi can only\b|\bi'?m only able to\b|"
    r"\b(?:refused|declined|denied|not permitted)\b|does not permit\b|can only be (?:accessed|seen|viewed) by\b|"
    r"(?:outside|out of) (?:my|the agent'?s) (?:scope|remit)|outside my scope\b|"
    r"\bnot (?:tracked|available|accessible|detailed|listed|recorded|held|captured|stored)\b"
    r"[^.]{0,25}?\b(?:in|to|through|by|via)\s+(?:my|our|the|this|these|your)\b|\bno access to\b|"
    r"(?:do(?:es)? not|don'?t|doesn'?t) (?:currently )?(?:cover|support)\b|\bnot covered\b|"
    r"blocked by policy|(?:this )?session is scoped to|scoped to (?:your|the|this) (?:signed-in )?store|"
    r"restricted to (?:store |district )?managers?|only (?:a )?(?:store |district )?manager|"
    r"must be (?:done|raised|created|submitted|approved) by (?:a |the )?(?:store |district )?manager|"
    r"(?:ask|contact|notify) your (?:store |district )?manager|a manager has to\b|"
    r"requires? (?:a |the )?(?:store |district )?manager(?: role)?\b|(?:need|needs) a manager role|"
    r"(?:a |the |your )?(?:store |district )?manager will (?:need|have) to\b|for (?:store |district )?managers only|"
    r"(?:stays?|remains?) (?:\w+ ){0,2}with (?:you\b[^.]{0,20}?)?(?:the )?(?:store |district )?(?:manager|hr|leadership)|"
    r"(?:is|are) not supported\b|\bnot (?:possible|available) (?:here|through this|in this)\b|"
    r"\bcan(?:no|\x27?)t be \w+(?: \w+)?,? (?:here|as only|because only|since only)\b|\bonly [^.]{0,60} (?:is|are) supported\b|"
    r"(?:please|first|need to|must|before i can|so i can)\s+sign in\b|sign in (?:with|using)\b|not signed in\b|"
    r"no (?:visibility|record|data|information) (?:of|on|for|about|in)\b",
    re.I)
# A hypothetical is not a decline either, even when it is attributed.
HYPOTHETICAL_RE = re.compile(r"\bif\b[^.;:\n]*", re.I)


MARKDOWN_EMPHASIS = re.compile(r"[*`]+")


def plain(text: str) -> str:
    """The answer without markdown emphasis, so "held for **5** days" still says "5 days" to a regex."""
    return MARKDOWN_EMPHASIS.sub("", text or "")


def declines(text: str) -> bool:
    """True when the answer says the agent will not or cannot do the thing that was asked."""
    return bool(REFUSAL_RE.search(HYPOTHETICAL_RE.sub(" ", text)))


class JourneyError(Exception):
    """A journey file (or a persona reference) is malformed; the message names the file and the fix."""


def load_personas(path: Path = PERSONAS_FILE) -> dict[str, dict]:
    raw = yaml.safe_load(path.read_text()) or {}
    personas = raw.get("personas")
    if not isinstance(personas, dict) or not personas:
        raise JourneyError(f"{path}: expected a non-empty `personas:` mapping")
    for key, p in personas.items():
        where = f"{path}: persona {key!r}"
        if not ID_RE.match(key):
            raise JourneyError(f"{where}: the key must be lowercase kebab-case (3-50 chars)")
        if not isinstance(p, dict):
            raise JourneyError(f"{where}: expected a mapping")
        unknown = set(p) - PERSONA_KEYS
        if unknown:
            raise JourneyError(f"{where}: unknown keys {sorted(unknown)}; allowed {sorted(PERSONA_KEYS)}")
        for required in ("name", "description"):
            if not str(p.get(required, "")).strip():
                raise JourneyError(f"{where}: `{required}` is required")
        if p.get("signed_in", True):
            for required in ("role", "associate_id", "store_id"):
                if not str(p.get(required, "")).strip():
                    raise JourneyError(f"{where}: `{required}` is required for a signed-in persona")
            if p["role"] not in ROLES:
                raise JourneyError(f"{where}: role must be one of {ROLES}, got {p['role']!r}")
        elif any(p.get(k) for k in ("role", "associate_id", "store_id")):
            raise JourneyError(f"{where}: signed_in: false means no role/associate_id/store_id")
    return personas


def persona_state(persona: dict) -> dict[str, str]:
    """The session state a signed-in device would seed. Identity never comes from the conversation."""
    if not persona.get("signed_in", True):
        return {}
    return {"user:user_id": persona["associate_id"], "user:store_id": persona["store_id"],
            "user:role": persona["role"], "user:first_name": persona["name"]}


def validate_journey(data: Any, personas: dict[str, dict], where: str) -> dict:
    if not isinstance(data, dict):
        raise JourneyError(f"{where}: expected a mapping at the top level")
    unknown = set(data) - JOURNEY_KEYS
    if unknown:
        raise JourneyError(f"{where}: unknown keys {sorted(unknown)}; allowed {sorted(JOURNEY_KEYS)}")
    missing = REQUIRED_JOURNEY_KEYS - set(data)
    if missing:
        raise JourneyError(f"{where}: missing required keys {sorted(missing)}")
    if not ID_RE.match(str(data["id"])):
        raise JourneyError(f"{where}: id {data['id']!r} must be lowercase kebab-case (3-50 chars)")
    if data["persona"] not in personas:
        raise JourneyError(f"{where}: persona {data['persona']!r} is not in personas.yaml ({sorted(personas)})")
    tags = data.get("tags") or []
    if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
        raise JourneyError(f"{where}: tags must be a list of strings")
    turns = data.get("turns")
    if data.get("kind") not in {None, "starter"}:
        raise JourneyError(f"{where}: kind must be starter when supplied")
    if data.get("kind") == "starter":
        if not isinstance(turns, list) or len(turns) != 1:
            raise JourneyError(f"{where}: a starter has exactly one turn")
    elif not isinstance(turns, list) or not 4 <= len(turns) <= 10:
        raise JourneyError(f"{where}: a journey has between 4 and 10 turns, got {len(turns or [])}")
    for i, turn in enumerate(turns, 1):
        _validate_turn(turn, f"{where}: turn {i}")
    return data


def _validate_turn(turn: Any, where: str) -> None:
    if not isinstance(turn, dict):
        raise JourneyError(f"{where}: expected a mapping")
    unknown = set(turn) - TURN_KEYS
    if unknown:
        raise JourneyError(f"{where}: unknown keys {sorted(unknown)}; allowed {sorted(TURN_KEYS)}")
    if not str(turn.get("say", "")).strip():
        raise JourneyError(f"{where}: `say` is required and must be what the person types")
    if not isinstance(turn.get("approve", False), bool):
        raise JourneyError(f"{where}: `approve` must be true or false")
    expect = turn.get("expect") or {}
    if not isinstance(expect, dict):
        raise JourneyError(f"{where}: `expect` must be a mapping")
    unknown = set(expect) - EXPECT_KEYS
    if unknown:
        raise JourneyError(f"{where}: unknown expectation keys {sorted(unknown)}; allowed {sorted(EXPECT_KEYS)}")
    if not expect:
        raise JourneyError(f"{where}: every turn needs at least one expectation, or it grades nothing")
    for key in LIST_EXPECT_KEYS & set(expect):
        value = expect[key]
        if not isinstance(value, list) or not value or any(not isinstance(v, str) for v in value):
            raise JourneyError(f"{where}: `{key}` must be a non-empty list of strings")
    for key in ("regex_all", "regex_none"):
        for pattern in expect.get(key) or []:
            try:
                re.compile(pattern)
            except re.error as e:
                raise JourneyError(f"{where}: `{key}` pattern {pattern!r} does not compile: {e}") from None
    if expect.get("tool_error_regex") is not None:
        try:
            re.compile(str(expect["tool_error_regex"]))
        except re.error as e:
            raise JourneyError(f"{where}: `tool_error_regex` does not compile: {e}") from None
    for key in ("refusal", "no_tool_errors"):
        if key in expect and not isinstance(expect[key], bool):
            raise JourneyError(f"{where}: `{key}` must be true or false")
    if "confirmation" in expect and expect["confirmation"] not in CONFIRMATION_VALUES:
        raise JourneyError(f"{where}: `confirmation` must be one of {CONFIRMATION_VALUES}")
    if "max_latency_s" in expect and not isinstance(expect["max_latency_s"], (int, float)):
        raise JourneyError(f"{where}: `max_latency_s` must be a number of seconds")
    if "state_has" in expect and not isinstance(expect["state_has"], dict):
        raise JourneyError(f"{where}: `state_has` must be a mapping of state key to expected value")


def load_journeys(directory: Path = JOURNEY_DIR, personas: dict[str, dict] | None = None) -> list[dict]:
    personas = personas if personas is not None else load_personas()
    journeys = []
    for path in sorted(directory.glob("*.yaml")):
        if path.name == PERSONAS_FILE.name:
            continue
        data = yaml.safe_load(path.read_text())
        journey = validate_journey(data, personas, str(path.relative_to(ROOT)))
        journey["_path"] = path
        journeys.append(journey)
    if not journeys:
        raise JourneyError(f"no journey files in {directory}")
    ids = [j["id"] for j in journeys]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise JourneyError(f"duplicate journey ids: {duplicates}")
    return journeys


# ---------------------------------------------------------------------------- targets
class LocalTarget:
    """In-process ADK runner over the same App that ships to Agent Runtime."""

    kind = "local"

    def __init__(self) -> None:
        from google.adk.runners import InMemoryRunner

        from agents.cymbal_store_ops.agent import app as adk_app
        self.app_name = adk_app.name
        self.runner = InMemoryRunner(app=adk_app)
        self.name = f"local:{self.app_name}"

    async def create_session(self, user_id: str, state: dict) -> str:
        session = await self.runner.session_service.create_session(app_name=self.app_name, user_id=user_id, state=state)
        return session.id

    def _message(self, payload: Any):
        from google.genai import types
        if isinstance(payload, str):
            return types.Content(role="user", parts=[types.Part(text=payload)])
        part = types.Part(function_response=types.FunctionResponse(
            id=payload["fc_id"], name=CONFIRMATION_TOOL, response={"confirmed": payload["confirmed"]}))
        return types.Content(role="user", parts=[part])

    async def stream(self, user_id: str, session_id: str, payload: Any, invocation_id: str | None) -> AsyncIterator[dict]:
        kwargs = {"invocation_id": invocation_id} if invocation_id else {}
        async for ev in self.runner.run_async(user_id=user_id, session_id=session_id,
                                              new_message=self._message(payload), **kwargs):
            yield ev.model_dump(mode="json", exclude_none=True)

    async def state(self, user_id: str, session_id: str) -> dict:
        session = await self.runner.session_service.get_session(app_name=self.app_name, user_id=user_id,
                                                                session_id=session_id)
        return dict(session.state) if session else {}


class RemoteTarget:
    """The deployed Agent Runtime for an environment (same session id across the journey's turns)."""

    kind = "remote"

    def __init__(self, env: str) -> None:
        from deployment._common import client_for, load_config, resolve_engine_name

        cfg = load_config(env)
        client = client_for(cfg)
        self.name = resolve_engine_name(cfg, client)
        self.remote = client.agent_engines.get(name=self.name)

    async def create_session(self, user_id: str, state: dict) -> str:
        session = await self.remote.async_create_session(user_id=user_id, state=state)
        return session["id"] if isinstance(session, dict) else session.id

    def _message(self, payload: Any):
        if isinstance(payload, str):
            return payload
        from google.genai import types
        part = types.Part(function_response=types.FunctionResponse(
            id=payload["fc_id"], name=CONFIRMATION_TOOL, response={"confirmed": payload["confirmed"]}))
        return {"role": "user", "parts": [part.model_dump(mode="json", exclude_none=True)]}

    async def stream(self, user_id: str, session_id: str, payload: Any, invocation_id: str | None) -> AsyncIterator[dict]:
        from deployment.streaming import stream_query

        async for ev in stream_query(name=self.name, user_id=user_id, session_id=session_id,
                                     message=self._message(payload), invocation_id=invocation_id):
            yield ev

    async def state(self, user_id: str, session_id: str) -> dict:
        session = await self.remote.async_get_session(user_id=user_id, session_id=session_id)
        raw = session if isinstance(session, dict) else session.__dict__
        return dict(raw.get("state") or {})


# ---------------------------------------------------------------------------- event reading
@dataclass
class TurnResult:
    index: int
    say: str
    approve: bool
    note: str = ""
    final_text: str = ""
    all_text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    tool_errors: list[dict] = field(default_factory=list)
    transfers: list[str] = field(default_factory=list)
    confirmations: list[dict] = field(default_factory=list)
    state_delta: dict = field(default_factory=dict)
    tokens: int = 0
    latency_s: float = 0.0
    checks: list[dict] = field(default_factory=list)
    runner_error: str = ""

    @property
    def tool_names(self) -> list[str]:
        return [c["name"] for c in self.tool_calls]

    @property
    def passed(self) -> bool:
        return not self.runner_error and all(c["ok"] for c in self.checks)


def _read_events(events: list[dict], result: TurnResult, answered: set[str]) -> dict | None:
    """Fold one round of events into the turn result; return the confirmation to answer, if any."""
    pending = None
    texts: list[tuple[str, str]] = []
    for ev in events:
        author = ev.get("author", "")
        actions = ev.get("actions") or {}
        if actions.get("transfer_to_agent"):
            result.transfers.append(actions["transfer_to_agent"])
        long_running = set(ev.get("long_running_tool_ids") or [])
        for part in (ev.get("content") or {}).get("parts") or []:
            call, response = part.get("function_call"), part.get("function_response")
            if call and call.get("name") == CONFIRMATION_TOOL:
                fc_id = call.get("id")
                if fc_id in long_running and fc_id not in answered:
                    original = (call.get("args") or {}).get("originalFunctionCall") or {}
                    entry = {"fc_id": fc_id, "invocation_id": ev.get("invocation_id"),
                             "tool": original.get("name"), "args": original.get("args") or {},
                             "hint": ((call.get("args") or {}).get("toolConfirmation") or {}).get("hint", "")}
                    result.confirmations.append(entry)
                    pending = pending or entry
            elif call:
                result.tool_calls.append({"author": author, "name": call.get("name"), "args": call.get("args") or {}})
            elif response and response.get("name") != CONFIRMATION_TOOL:
                payload = response.get("response") or {}
                status = str(payload.get("status", "")).upper()
                if status == "ERROR" or "error_details" in payload or "error" in payload:
                    result.tool_errors.append({"name": response.get("name"),
                                               "details": str(payload.get("error_details") or payload.get("error") or payload)[:400]})
            elif part.get("text") and not ev.get("partial"):
                texts.append((author, part["text"]))
        delta = {k: v for k, v in (actions.get("state_delta") or {}).items() if not k.startswith("_")}
        result.state_delta.update(delta)
        usage = ev.get("usage_metadata") or {}
        result.tokens += int(usage.get("total_token_count") or 0)
    result.all_text += "\n".join(t for _, t in texts)
    if texts:
        last_author = texts[-1][0]
        trailing: list[str] = []
        for author, text in reversed(texts):
            if author != last_author:
                break
            trailing.append(text)
        result.final_text = "\n".join(reversed(trailing)).strip()
    return pending


async def run_turn(target, user_id: str, session_id: str, turn: dict, index: int) -> TurnResult:
    result = TurnResult(index=index, say=str(turn["say"]), approve=bool(turn.get("approve", False)),
                        note=str(turn.get("note", "")))
    payload: Any = result.say
    invocation_id: str | None = None
    answered: set[str] = set()
    start = time.perf_counter()
    try:
        for _ in range(MAX_CONFIRMATION_ROUNDS):
            events = [ev async for ev in target.stream(user_id, session_id, payload, invocation_id)]
            pending = _read_events(events, result, answered)
            if not pending:
                break
            answered.add(pending["fc_id"])
            payload = {"fc_id": pending["fc_id"], "confirmed": result.approve}
            invocation_id = pending["invocation_id"]
        else:
            retried = ", ".join(sorted({c["tool"] or "?" for c in result.confirmations}))
            result.runner_error = (
                f"more than {MAX_CONFIRMATION_ROUNDS} confirmation rounds in one turn: {retried} kept asking "
                f"after the answer was {'yes' if result.approve else 'no'}")
    except Exception as e:  # noqa: BLE001 — recorded in the transcript, never swallowed
        result.runner_error = f"{type(e).__name__}: {e}"
    result.latency_s = time.perf_counter() - start
    return result


# ---------------------------------------------------------------------------- grading
def _check(checks: list[dict], name: str, ok: bool, detail: str) -> None:
    """`detail` says what was actually seen, whether the check passed or failed — a reviewer reads both."""
    checks.append({"name": name, "ok": bool(ok), "detail": detail})


def _found(ok: bool, where: str) -> str:
    return f"found in {where}" if ok else f"not in {where}"


def _absent(ok: bool, where: str) -> str:
    return f"absent from {where}" if ok else f"present in {where}"


def grade(result: TurnResult, expect: dict, state: dict) -> None:
    """Positive checks read the final answer; negative checks read every text the turn produced."""
    final, everything = plain(result.final_text), plain(result.all_text)
    names = result.tool_names
    seen = f"tools called: {names or 'none'}"
    for tool in expect.get("tools_all") or []:
        _check(result.checks, f"tools_all:{tool}", tool in names, seen)
    if expect.get("tools_any"):
        wanted = expect["tools_any"]
        _check(result.checks, f"tools_any:{'|'.join(wanted)}", any(t in names for t in wanted), seen)
    for tool in expect.get("tools_none") or []:
        _check(result.checks, f"tools_none:{tool}", tool not in names, seen)
    for phrase in expect.get("contains_all") or []:
        ok = phrase.lower() in final.lower()
        _check(result.checks, f"contains:{phrase!r}", ok, _found(ok, "the final answer"))
    if expect.get("contains_any"):
        wanted = expect["contains_any"]
        hits = [p for p in wanted if p.lower() in final.lower()]
        _check(result.checks, f"contains_any:{wanted}", bool(hits),
               f"matched {hits}" if hits else "none of them in the final answer")
    for phrase in expect.get("not_contains") or []:
        ok = phrase.lower() not in everything.lower()
        _check(result.checks, f"not_contains:{phrase!r}", ok, _absent(ok, "the turn's text"))
    for pattern in expect.get("regex_all") or []:
        match = re.search(pattern, final, re.I | re.S)
        _check(result.checks, f"regex:{pattern!r}", bool(match),
               f"matched {match.group(0)[:60]!r}" if match else "no match in the final answer")
    for pattern in expect.get("regex_none") or []:
        match = re.search(pattern, everything, re.I | re.S)
        _check(result.checks, f"regex_none:{pattern!r}", not match,
               f"matched {match.group(0)[:60]!r} in the turn's text" if match else "no match in the turn's text")
    if "refusal" in expect:
        declined = declines(final)
        _check(result.checks, f"refusal:{expect['refusal']}", declined == bool(expect["refusal"]),
               f"the answer {'declines' if declined else 'does not decline'}")
    if expect.get("no_tool_errors"):
        _check(result.checks, "no_tool_errors", not result.tool_errors,
               "; ".join(f"{e['name']}: {e['details'][:120]}" for e in result.tool_errors) or "no tool returned an error")
    if expect.get("tool_error_regex"):
        pattern = str(expect["tool_error_regex"])
        blob = " | ".join(f"{e['name']}: {e['details']}" for e in result.tool_errors)
        _check(result.checks, f"tool_error_regex:{pattern!r}", bool(re.search(pattern, blob, re.I)),
               f"tool errors: {blob or 'none'}")
    if expect.get("confirmation"):
        asked = bool(result.confirmations)
        want = expect["confirmation"] == "required"
        _check(result.checks, f"confirmation:{expect['confirmation']}", asked == want,
               f"{len(result.confirmations)} confirmation(s) requested")
    if expect.get("max_latency_s"):
        limit = float(expect["max_latency_s"])
        _check(result.checks, f"max_latency_s:{limit:g}", result.latency_s <= limit, f"{result.latency_s:.1f}s")
    for key, value in (expect.get("state_has") or {}).items():
        _check(result.checks, f"state_has:{key}", str(state.get(key, "")) == str(value),
               f"state[{key}] = {state.get(key, '<missing>')!r}")
    if result.runner_error:
        _check(result.checks, "runner", False, result.runner_error)


# ---------------------------------------------------------------------------- running
@dataclass
class JourneyResult:
    journey: dict
    persona: dict
    session_id: str = ""
    turns: list[TurnResult] = field(default_factory=list)
    error: str = ""

    @property
    def passed(self) -> bool:
        return not self.error and all(t.passed for t in self.turns)


async def run_journey(target, journey: dict, personas: dict[str, dict]) -> JourneyResult:
    persona = personas[journey["persona"]]
    out = JourneyResult(journey=journey, persona=persona)
    user_id = f"journey-{journey['id']}"
    try:
        out.session_id = await target.create_session(user_id, persona_state(persona))
    except Exception as e:  # noqa: BLE001
        out.error = f"could not create a session: {type(e).__name__}: {e}"
        return out
    for i, turn in enumerate(journey["turns"], 1):
        result = await run_turn(target, user_id, out.session_id, turn, i)
        expect = turn.get("expect") or {}
        state: dict = {}
        if expect.get("state_has"):   # one extra round-trip against a deployed engine; only fetch it when graded
            try:
                state = await target.state(user_id, out.session_id)
            except Exception as e:  # noqa: BLE001
                result.runner_error = result.runner_error or f"could not read session state: {type(e).__name__}: {e}"
        grade(result, expect, state)
        out.turns.append(result)
        print(f"  {journey['id']} turn {i}/{len(journey['turns'])} "
              f"{'PASS' if result.passed else 'FAIL'} {result.latency_s:5.1f}s  {result.say[:60]}", flush=True)
    return out


# ---------------------------------------------------------------------------- reporting
def _fence(text: str, limit: int = 4000) -> str:
    body = text.strip() or "(no text)"
    if len(body) > limit:
        body = body[:limit] + "\n… (truncated)"
    return "```\n" + body.replace("```", "'''") + "\n```"


def write_transcript(result: JourneyResult, target_name: str, out_dir: Path) -> Path:
    j, p = result.journey, result.persona
    lines = [f"# {j['title']}", "",
             f"- **journey**: `{j['id']}`  ", f"- **persona**: {p['name']} — {p['description']}  ",
             f"- **goal**: {j['goal']}  ",
             f"- **target**: `{target_name}`  session `{result.session_id or 'none'}`  ",
             f"- **result**: {'PASS' if result.passed else 'FAIL'} "
             f"({sum(1 for t in result.turns if t.passed)}/{len(result.turns)} turns)", ""]
    if j.get("notes"):
        lines += [f"> {j['notes']}", ""]
    if result.error:
        lines += [f"**Runner error:** {result.error}", ""]
    for t in result.turns:
        lines += [f"## Turn {t.index} — {'PASS' if t.passed else 'FAIL'} ({t.latency_s:.1f}s"
                  + (f", {t.tokens} tokens" if t.tokens else "") + ")", ""]
        if t.note:
            lines += [f"*{t.note}*", ""]
        lines += [f"**{p['name']} says**", "", _fence(t.say), "", "**Agent answers**", "", _fence(t.final_text), ""]
        if t.tool_calls:
            lines += ["**Tools**", ""]
            lines += [f"- `{c['name']}` ({c['author']}) {json.dumps(c['args'], ensure_ascii=False)[:200]}"
                      for c in t.tool_calls]
            lines += [""]
        if t.transfers:
            lines += [f"**Transfers**: {', '.join(t.transfers)}", ""]
        if t.confirmations:
            lines += ["**Confirmations** (answered "
                      + ("yes" if t.approve else "no") + ")", ""]
            lines += [f"- `{c['tool']}` — {c['hint']}" for c in t.confirmations]
            lines += [""]
        if t.tool_errors:
            lines += ["**Tool errors**", ""]
            lines += [f"- `{e['name']}`: {e['details'][:300]}" for e in t.tool_errors]
            lines += [""]
        if t.state_delta:
            lines += [f"**State delta**: `{json.dumps(t.state_delta, default=str)[:400]}`", ""]
        if t.checks:
            lines += ["**Expectations**", "", "| check | result | detail |", "| --- | --- | --- |"]
            lines += [f"| `{c['name']}` | {'pass' if c['ok'] else '**FAIL**'} | {c['detail'][:160]} |" for c in t.checks]
            lines += [""]
        if t.runner_error:
            lines += [f"**Runner error:** {t.runner_error}", ""]
    path = out_dir / f"{j['id']}.md"
    path.write_text("\n".join(lines))
    return path


def write_summary(results: list[JourneyResult], target_name: str, out_dir: Path, elapsed: float) -> Path:
    latencies = sorted(t.latency_s for r in results for t in r.turns)
    tokens = sum(t.tokens for r in results for t in r.turns)
    turns = len(latencies)
    failed_turns = [(r, t) for r in results for t in r.turns if not t.passed]

    def pct(p: float) -> float:
        if not latencies:
            return 0.0
        k = max(0, min(len(latencies) - 1, round(p / 100 * (len(latencies) - 1))))
        return latencies[k]

    lines = ["# Journey run summary", "",
             f"- target: `{target_name}`", f"- journeys: {len(results)}  turns: {turns}",
             f"- journeys passed: {sum(1 for r in results if r.passed)}/{len(results)}",
             f"- turns passed: {turns - len(failed_turns)}/{turns}",
             f"- wall clock: {elapsed:.0f}s", ""]
    if latencies:
        lines += [f"- latency per turn: p50 {pct(50):.1f}s  p95 {pct(95):.1f}s  max {latencies[-1]:.1f}s  "
                  f"mean {statistics.fmean(latencies):.1f}s"]
    lines += [f"- tokens reported: {tokens or 'not reported by this target'}", "",
              "## Journeys", "", "| journey | persona | turns | passed | worst latency | first failing turn |",
              "| --- | --- | --- | --- | --- | --- |"]
    for r in results:
        worst = max((t.latency_s for t in r.turns), default=0.0)
        first_fail = next((t.index for t in r.turns if not t.passed), None)
        lines.append(f"| [{r.journey['id']}]({r.journey['id']}.md) | {r.persona['name']} ({r.persona.get('role', 'no sign-in')}) | "
                     f"{len(r.turns)} | {sum(1 for t in r.turns if t.passed)}/{len(r.turns)} | {worst:.1f}s | "
                     f"{first_fail if first_fail else '—'} |")
    lines += ["", "## Turn grid", "", "| journey | " + " | ".join(str(i) for i in range(1, 11)) + " |",
              "| --- |" + " --- |" * 10]
    for r in results:
        cells = []
        for i in range(1, 11):
            turn = next((t for t in r.turns if t.index == i), None)
            cells.append("·" if turn is None else ("pass" if turn.passed else "**FAIL**"))
        lines.append(f"| {r.journey['id']} | " + " | ".join(cells) + " |")
    if failed_turns:
        lines += ["", "## Failed expectations", ""]
        for r, t in failed_turns:
            for c in t.checks:
                if not c["ok"]:
                    lines.append(f"- `{r.journey['id']}` turn {t.index} — `{c['name']}` — {c['detail'][:200]}")
    path = out_dir / "summary.md"
    path.write_text("\n".join(lines) + "\n")
    return path


# ---------------------------------------------------------------------------- CLI
def select(journeys: list[dict], ids: list[str], tags: list[str]) -> list[dict]:
    chosen = journeys
    if ids:
        known = {j["id"] for j in journeys}
        unknown = sorted(set(ids) - known)
        if unknown:
            raise JourneyError(f"unknown journey id(s) {unknown}; available: {sorted(known)}")
        chosen = [j for j in chosen if j["id"] in ids]
    if tags:
        chosen = [j for j in chosen if set(j.get("tags") or []) & set(tags)]
        if not chosen:
            raise JourneyError(f"no journey carries any of the tags {tags}")
    return chosen


async def run_all(target, journeys: list[dict], personas: dict[str, dict], concurrency: int,
                  out_dir: Path) -> list[JourneyResult]:
    """Read-only journeys run concurrently; journeys that write run one at a time afterwards.

    Each transcript is written as its journey finishes, so a long run can be read while it is still going."""
    parallel = [j for j in journeys if not j.get("writes")]
    serial = [j for j in journeys if j.get("writes")]
    results: dict[str, JourneyResult] = {}
    gate = asyncio.Semaphore(max(1, concurrency))

    async def one(journey: dict) -> None:
        result = await run_journey(target, journey, personas)
        results[journey["id"]] = result
        path = write_transcript(result, target.name, out_dir)
        print(f"  {journey['id']}: {'PASS' if result.passed else 'FAIL'} -> {path}", flush=True)

    async def guarded(journey: dict) -> None:
        async with gate:
            await one(journey)

    if parallel:
        print(f"running {len(parallel)} read-only journey(s), {concurrency} at a time", flush=True)
        await asyncio.gather(*(guarded(j) for j in parallel))
    for journey in serial:
        print(f"running writing journey {journey['id']} on its own", flush=True)
        await one(journey)
    return [results[j["id"]] for j in journeys if j["id"] in results]


def main(argv: list[str] | None = None) -> int:
    from agents.cymbal_store_ops.preflight import require_sign_in

    require_sign_in()   # an expired sign-in stops here, in words, not as a stack trace later
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--journey", action="append", default=[], help="journey id (repeatable); default: all")
    ap.add_argument("--tag", action="append", default=[], help="only journeys carrying this tag (repeatable)")
    ap.add_argument("--target", choices=["local", "remote"], default="local")
    ap.add_argument("--env", default="dev", help="environment for --target remote")
    ap.add_argument("--out", default=str(OUT_DIR), help="output directory for transcripts")
    ap.add_argument("--concurrency", type=int, default=4, help="read-only journeys to run at once")
    ap.add_argument("--list", action="store_true", help="list the journeys and exit")
    args = ap.parse_args(argv)

    try:
        personas = load_personas()
        journeys = select(load_journeys(personas=personas), args.journey, args.tag)
    except JourneyError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if args.list:
        for j in journeys:
            tags = ",".join(j.get("tags") or []) or "-"
            print(f"{j['id']:<32} {len(j['turns'])} turns  {j['persona']:<22} [{tags}]  {j['title']}")
        return 0

    try:
        target = RemoteTarget(args.env) if args.target == "remote" else LocalTarget()
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: could not open the {args.target} target: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"target {target.name}; writing transcripts to {out_dir}", flush=True)
    start = time.perf_counter()
    results = asyncio.run(run_all(target, journeys, personas, args.concurrency, out_dir))
    elapsed = time.perf_counter() - start
    summary = write_summary(results, target.name, out_dir, elapsed)

    failed = [r for r in results if not r.passed]
    print(f"\n{len(results) - len(failed)}/{len(results)} journeys passed in {elapsed:.0f}s — {summary}")
    for r in failed:
        bad = [t for t in r.turns if not t.passed]
        print(f"  FAIL {r.journey['id']}: turn(s) {', '.join(str(t.index) for t in bad)}"
              + (f" — {r.error}" if r.error else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
