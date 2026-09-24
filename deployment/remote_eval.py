"""Run the golden prompts against a deployed engine or one revision and record the evidence.

    uv run python deployment/remote_eval.py --env dev [--revision <name>]  -> build/remote_eval.<env>.json

Checks scoped successful reads, identity, approval boundaries and factual answers.
Operational reads may use any supported evidence path. Exit 1 if any prompt fails.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.cymbal_store_ops.mcp_result import MCP_READ_NAMES, normalize_tool_result  # noqa: E402
from deployment._common import (  # noqa: E402
    ENVS,
    REPO_ROOT,
    DeployError,
    client_for,
    load_config,
    now_iso,
    read_deployment_info,
    resolve_engine_name,
)
from deployment.smoke import stream_events  # noqa: E402
from eval.metrics import STRICT_WORKFLOWS, _completed_briefing, _read_call  # noqa: E402

WRITE_TOOLS = {"create_store_task", "delegate_task", "complete_my_task", "report_my_task_blocker"}


def collect(events):
    """Keep actual tool call/result IDs and confirmation pauses; never submit approval."""
    calls, responses, confirmations, final = [], [], [], ""
    for event in events:
        long_running = set(event.get("long_running_tool_ids") or [])
        for part in (event.get("content") or {}).get("parts") or []:
            if part.get("thought"):
                continue
            if fc := part.get("function_call"):
                calls.append(SimpleNamespace(name=fc.get("name", ""), id=fc.get("id"), args=fc.get("args") or {}))
                if fc.get("name") == "adk_request_confirmation" and fc.get("id") in long_running:
                    confirmations.append(fc)
            if fr := part.get("function_response"):
                responses.append(SimpleNamespace(name=fr.get("name", ""), id=fr.get("id"), response=normalize_tool_result(fr.get("name", ""), fr.get("response") or {})))
            if part.get("text") and not event.get("partial"):
                final = part["text"]
    return calls, responses, confirmations, final


def assess(probe, evidence):
    calls, responses, confirmations, final = evidence
    names = [c.name for c in calls]
    matched = [(call, response) for call in calls for response in responses
               if call.id and call.id == response.id and call.name == response.name]
    successes = {call.name for call, response in matched
                 if response.response.get("status") == "SUCCESS" and not response.response.get("error_details")}
    errors = [response.name for response in responses
              if response.response.get("status") == "ERROR" or response.response.get("error_details")]
    reasons = ["tool_error"] if errors else []
    strict = (set(probe.get("expect_tools", [])) | set(probe.get("expect_success", []))) & STRICT_WORKFLOWS
    # Consultant routing is model-selected. Identity and approval/write contracts remain strict.
    for name in strict - {"store_tasks"}:
        if name not in names or (name in probe.get("expect_success", []) and name not in successes):
            reasons.append("missing_required_control:" + name)
    read_required = bool(set(probe.get("expect_tools", [])) - STRICT_WORKFLOWS or
                         set(probe.get("expect_success", [])) - STRICT_WORKFLOWS)
    read_evidence = []
    for call, response in matched:
        native_name = MCP_READ_NAMES.get(call.name, call.name)
        native = SimpleNamespace(name=native_name, id=call.id, args=call.args)
        if ((_read_call(native) and response.response.get("status") == "SUCCESS"
             and not response.response.get("error_details")) or _completed_briefing(call, [response])):
            read_evidence.append(call.name)
    if read_required and not read_evidence:
        reasons.append("missing_successful_store_read")
    if "store_tasks" in strict and not confirmations:
        reasons.append("missing_confirmation_pause")
    # Every probe is one unsigned turn; no continuation ever approves a write.
    if successes & WRITE_TOOLS:
        reasons.append("write_without_confirmation")
    if any(t in names for t in probe.get("expect_no_tools", [])):
        reasons.append("forbidden_tool")
    if probe.get("require_final_text") and not final.strip():
        reasons.append("missing_final_text")
    if probe.get("final_text_contains_any") and not any(s.lower() in final.lower() for s in probe["final_text_contains_any"]):
        reasons.append("missing_answer_fact")
    if probe.get("final_text_matches") and not re.search(probe["final_text_matches"], final, re.I):
        reasons.append("answer_fact_mismatch")
    return {"id": probe["id"], "ok": not reasons, "failures": reasons, "tool_calls": names,
            "tool_errors": errors, "successful_reads": read_evidence, "confirmation_count": len(confirmations), "final": final}



def main() -> int:
    from agents.cymbal_store_ops.preflight import require_sign_in

    require_sign_in()   # an expired sign-in stops here, in words, not as a stack trace later
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--env", required=True, choices=ENVS)
    ap.add_argument("--revision", default=None)
    a = ap.parse_args()
    cfg = load_config(a.env)
    client = client_for(cfg)
    name = resolve_engine_name(cfg, client)
    target = client.agent_engines.runtimes.revisions.get(name=a.revision) if a.revision else client.agent_engines.get(name=name)
    spec = json.loads((REPO_ROOT / "eval" / "golden_prompts.json").read_text())
    results, failures = [], 0
    for i, p in enumerate(spec["prompts"]):
        evidence = collect(stream_events(target, p["prompt"], user_id=f"remote-eval-{i}"))
        result = assess(p, evidence)
        failures += not result["ok"]
        results.append(result)
        print(f"[{'PASS' if result['ok'] else 'FAIL'}] {p['id']}: tools={result['tool_calls']}"
              + (f" failures={result['failures']}" if not result["ok"] else ""))
    out = REPO_ROOT / "build" / f"remote_eval.{a.env}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"env": a.env, "target": a.revision or name, "release": read_deployment_info(a.env),
                               "ran_at": now_iso(), "results": results}, indent=2, ensure_ascii=False))
    print(f"wrote {out}: {len(results) - failures}/{len(results)} passed")
    if failures:
        raise DeployError(f"{failures} golden prompt(s) failed against {a.revision or name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
