"""Smoke-test a deployed engine (or one revision) with a real query.

    uv run python deployment/smoke.py --env dev [--revision <full revision name>] [--prompt "..."]

Checks successful store reads and the fixture on-hand count, allowing the model to select its evidence path. Exit 1 on failure.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.cymbal_store_ops import fixtures as F  # noqa: E402
from agents.cymbal_store_ops.mcp_result import normalize_tool_result  # noqa: E402
from deployment._common import (  # noqa: E402
    ENVS,
    DeployError,
    client_for,
    load_config,
    resolve_engine_name,
)

DEFAULT_PROMPT = f"I'm {F.HERO_MANAGER_ID} at {F.HERO_STORE_CITY}. Why is {F.HERO_PRODUCT_NAME} flagged?"


def stream_events(target, prompt: str, user_id: str):
    """Use the shared REST decoder for engines and pinned runtime revisions."""
    from deployment.streaming import stream_query

    async def run():
        session = await target.async_create_session(user_id=user_id)
        session_id = session["id"] if isinstance(session, dict) else session.id
        return [event async for event in stream_query(name=target.api_resource.name,
            user_id=user_id, session_id=session_id, message=prompt)]

    return asyncio.run(run())


def stream(target, prompt: str, user_id: str = "smoke") -> tuple[list[str], str, list[str], list[str]]:
    """Return (tool calls in order, final text, tools that answered status ERROR, tools that answered SUCCESS)."""
    calls, final, errors, successes = [], "", [], []
    for ev in stream_events(target, prompt, user_id):
        content = ev.get("content") or {}
        for part in content.get("parts") or []:
            fc = part.get("function_call")
            if fc:
                calls.append(fc.get("name", "?"))
            fr = part.get("function_response")
            if fr and isinstance(fr.get("response"), dict):
                result = normalize_tool_result(fr.get("name", ""), fr["response"])
                if result.get("status") == "ERROR":
                    errors.append(fr.get("name", "?"))
                elif result.get("status") == "SUCCESS":
                    successes.append(fr.get("name", "?"))
            if part.get("text") and not part.get("thought") and not ev.get("partial"):
                final = part["text"]
    return calls, final, errors, successes


def main() -> int:
    from agents.cymbal_store_ops.preflight import require_sign_in

    require_sign_in()   # an expired sign-in stops here, in words, not as a stack trace later
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", required=True, choices=ENVS)
    ap.add_argument("--revision", default=None, help="query one revision directly (bypasses the traffic split)")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--expect-tool", default="", help="Optional named-tool assertion for a focused capability check")
    ap.add_argument("--expect-text", default=str(F.HERO_STORE_ON_HAND), help="must appear in the final answer")
    a = ap.parse_args()
    cfg = load_config(a.env)
    client = client_for(cfg)
    name = resolve_engine_name(cfg, client)
    target = client.agent_engines.runtimes.revisions.get(name=a.revision) if a.revision else client.agent_engines.get(name=name)
    calls, final, errors, successes = stream(target, a.prompt)
    out = {"env": a.env, "target": a.revision or name, "prompt": a.prompt, "tool_calls": calls, "tool_errors": errors, "final": final[:400]}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    if a.expect_tool and a.expect_tool not in calls:
        raise DeployError(f"expected a {a.expect_tool!r} tool call, saw {calls}")
    evidence = set(successes) - {"identify_demo_user", "workshop_clock", "describe_store_data", "store_mcp_describe_store_data"}
    if not evidence:
        raise DeployError("No successful store-data read was recorded.")
    if errors:
        raise DeployError(f"tool(s) returned status ERROR on the engine: {errors} (read the engine logs)")
    if not final.strip():
        engine_id = name.rsplit("/", 1)[-1]
        raise DeployError(
            f"the run ended without an answer after {calls}: a tool raised on the engine (for example a 403 on a data "
            f"source the runtime identity cannot read). Read the engine logs: gcloud logging read "
            f"'resource.type=\"aiplatform.googleapis.com/ReasoningEngine\" AND resource.labels.reasoning_engine_id=\"{engine_id}\" "
            f"AND severity>=ERROR' --project {cfg.project} --freshness=15m --limit 5")
    if a.expect_text and a.expect_text not in final:
        raise DeployError(f"expected {a.expect_text!r} in the final answer (a tool error or a guess, not the fixture)")
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
