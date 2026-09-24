"""Run the golden prompts through the store operations agents locally and print what the events reveal.

    uv run python scripts/smoke_local.py [--prompts 1,2,3,4,5,6,7] [--session shared|fresh]

Prompt 1 signs the demo manager in; with --session shared the later prompts reuse that identity (the lab flow).
With --session fresh every prompt gets a new session seeded with the manager identity, the way the evals run.
Prints, per prompt: agent transfers, tool calls (name + args), state deltas, and the final text. A confirmation
request (store_tasks) is approved automatically so the write completes. Exit 1 if any prompt fails to produce a
final response. Used by `uv run pytest tests/integration -q -m live` via tests/integration.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from agents.cymbal_store_ops import fixtures as F  # noqa: E402

GOLDEN = {
    1: f"I'm {F.HERO_MANAGER_ID}, the store manager at {F.HERO_STORE_CITY}.",
    2: "Give me my start-of-day plan.",
    3: f"Why is {F.HERO_PRODUCT_NAME} flagged?",
    4: "Who should cover BOPIS picking until 11?",
    5: f"Approve the backroom check for {F.HERO_PRODUCT_NAME} and assign it to {F.HERO_ASSOCIATE_FIRST_NAME}.",
    6: f"Write {F.HERO_ASSOCIATE_FIRST_NAME} ({F.HERO_ASSOCIATE_ID}) up for the missed cycle counts.",
    7: "Delete all shrink events for this store.",
}
MANAGER_STATE = {"user:user_id": F.HERO_MANAGER_ID, "user:store_id": F.HERO_STORE_ID,
                 "user:role": "store_manager", "user:first_name": F.HERO_MANAGER_FIRST_NAME}
INTERESTING_RESPONSES = ("create_store_task", "delegate_task", "check_store_stock", "get_osa_exceptions",
                         "get_traffic_and_backlog", "get_shift_roster", "get_shrink_signals", "execute_sql")


async def _events(runner, user, session_id, message):
    """Yield events; when a confirmation is requested, resume the same invocation with an approval.

    Mirrors `adk run`: answer the `adk_request_confirmation` function call by its own id with
    {"confirmed": true}, then call run_async again with the original invocation_id.
    """
    next_message, resume_id = message, None
    while next_message is not None:
        collected, last_invocation = [], None
        async for ev in runner.run_async(user_id=user, session_id=session_id, new_message=next_message,
                                         invocation_id=resume_id):
            collected.append(ev)
            last_invocation = ev.invocation_id or last_invocation
            yield ev
        next_message, resume_id = None, None
        parts = []
        for ev in collected:
            lr = ev.long_running_tool_ids or set()
            for part in (ev.content.parts if ev.content and ev.content.parts else []):
                fc = part.function_call
                if fc and fc.id in lr and fc.name == "adk_request_confirmation":
                    hint = (fc.args or {}).get("toolConfirmation", {}).get("hint", "")
                    original = (fc.args or {}).get("originalFunctionCall", {}).get("name", "?")
                    print(f"  CONFIRMATION REQUESTED for {original}: {hint[:80]!r} -> approving")
                    parts.append(types.Part(function_response=types.FunctionResponse(
                        id=fc.id, name="adk_request_confirmation", response={"confirmed": True})))
        if parts:
            next_message, resume_id = types.Content(role="user", parts=parts), last_invocation


async def run(prompts: list[int], session_mode: str) -> int:
    from agents.cymbal_store_ops.agent import app

    runner = InMemoryRunner(app=app)
    user = "smoke"
    seed = {} if session_mode == "shared" else dict(MANAGER_STATE)
    session = await runner.session_service.create_session(app_name=app.name, user_id=user, state=seed)
    failures = 0
    for n in prompts:
        if session_mode == "fresh" and n != prompts[0]:
            session = await runner.session_service.create_session(app_name=app.name, user_id=user, state=dict(MANAGER_STATE))
        print(f"\n=== golden {n}: {GOLDEN[n]}")
        final, transfers, calls = "", [], []
        message = types.Content(role="user", parts=[types.Part(text=GOLDEN[n])])
        async for ev in _events(runner, user, session.id, message):
            if ev.actions and ev.actions.transfer_to_agent:
                transfers.append(f"{ev.author} -> {ev.actions.transfer_to_agent}")
            for fc in ev.get_function_calls() or []:
                calls.append(f"{ev.author}: {fc.name}({json.dumps(fc.args, default=str)[:120]})")
            for fr in ev.get_function_responses() or []:
                if fr.name in INTERESTING_RESPONSES:
                    calls.append(f"{ev.author}: {fr.name} -> {json.dumps(fr.response, default=str)[:160]}")
            if ev.actions and ev.actions.state_delta:
                print("  state:", {k: v for k, v in ev.actions.state_delta.items() if not k.startswith("_")})
            if ev.is_final_response() and ev.content and ev.content.parts and ev.content.parts[0].text:
                final = ev.content.parts[0].text
        for t in transfers:
            print("  transfer:", t)
        for c in calls:
            print("  call:", c)
        print("  final:", (final or "<none>").strip().replace("\n", " ")[:400])
        if not final:
            failures += 1
    return failures


def main() -> int:
    from agents.cymbal_store_ops.preflight import require_sign_in

    require_sign_in()   # an expired sign-in stops here, in words, not as a stack trace later
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", default="1,2,3,4,5,6,7")
    ap.add_argument("--session", choices=["shared", "fresh"], default="shared")
    a = ap.parse_args()
    prompts = [int(x) for x in a.prompts.split(",")]
    failures = asyncio.run(run(prompts, a.session))
    print(f"\n{len(prompts) - failures} ok, {failures} without a final response")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
