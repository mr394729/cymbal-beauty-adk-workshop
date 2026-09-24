"""Exercise model-generated next actions rather than a scripted second user turn.

Starts each persona/scenario, validates the returned actions, then sends one actual generated
request back to the same session. All write confirmations are declined. The transcript records
the choices and responses for decision-quality review; execution checks are not a semantic judge.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.cymbal_store_ops.chat_reply import NextAction  # noqa: E402
from frontend.server import DEMO_IDENTITIES  # noqa: E402
from journeys.run import LocalTarget, RemoteTarget, run_turn  # noqa: E402


def validate_actions(actions: list[dict]) -> list[dict]:
    if not 3 <= len(actions) <= 5:
        raise ValueError(f"Expected 3–5 generated actions, received {len(actions)}")
    parsed = [NextAction.model_validate(action).model_dump() for action in actions]
    prompts = [action["prompt"].strip().casefold() for action in parsed]
    if not all(prompts) or len(set(prompts)) != len(prompts):
        raise ValueError("Suggested actions must be non-empty and distinct")
    if any(not action["label"].strip() for action in parsed):
        raise ValueError("Suggested actions need readable labels")
    return parsed


async def scenario_run(target, scenario: dict, action_index: int, out: Path) -> dict:
    uid = f"suggestions-{scenario['id']}"
    identity = DEMO_IDENTITIES[scenario["sign_in"]]
    sid = await target.create_session(uid, dict(identity))
    turns = []
    prompt = scenario["prompts"][0]["say"]
    for index in range(2):
        result = await run_turn(target, uid, sid, {"say": prompt, "approve": False}, index + 1)
        state = await target.state(uid, sid)
        # Preserve each actual turn before grading, including failures and recovered errors.
        (out / f"{scenario['id']}-turn-{index + 1}.json").write_text(json.dumps(
            {"scenario": scenario["id"], "session_id": sid, "turn": asdict(result)},
            ensure_ascii=False, indent=2))
        errors = [error for error in result.tool_errors if "rejected" not in error["details"].casefold()]
        if errors or result.runner_error or not result.final_text:
            raise ValueError(f"{scenario['id']}: failed generated conversation: {errors or result.runner_error or 'empty answer'}")
        if len(result.confirmations) > 1:
            raise ValueError("A declined action was proposed for approval again in the same turn")
        returned_actions = result.state_delta.get("ui:next_actions", [])
        # A deterministic cancellation ends the action without inventing follow-up chips.
        actions = [] if result.confirmations and not returned_actions else validate_actions(returned_actions)
        if any(state.get(key) != value for key, value in identity.items()):
            raise ValueError("Conversation changed the signed-in identity")
        if scenario["sign_in"] == "associate" and any(name in result.tool_names for name in ("create_store_task", "delegate_task", "get_coaching_signals")):
            raise ValueError("Associate suggestion attempted a manager-only capability")
        turns.append({**asdict(result), "next_actions": actions})
        if index == 0:
            if not actions:
                raise ValueError("The scenario starter did not supply an action to exercise")
            prompt = actions[action_index % len(actions)]["prompt"]
    return {"scenario": scenario["id"], "persona": scenario["sign_in"], "turns": turns, "passed": True}


async def main(args):
    target = RemoteTarget(args.env) if args.target == "remote" else LocalTarget()
    scenarios = yaml.safe_load((ROOT / "frontend/scenarios.yaml").read_text())["scenarios"]
    if args.scenario:
        scenarios = [scenario for scenario in scenarios if scenario["id"] in args.scenario]
        if {scenario["id"] for scenario in scenarios} != set(args.scenario):
            raise ValueError("Unknown scenario identifier")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(args.concurrency)
    async def run(scenario):
        async with semaphore:
            try:
                result = await scenario_run(target, scenario, args.action_index, out)
            except Exception as error:  # noqa: BLE001 — preserve failure in the evaluation report
                result = {"scenario": scenario["id"], "passed": False, "error": f"{type(error).__name__}: {error}"}
            print(f"{scenario['id']}: {'PASS' if result['passed'] else 'FAIL'}", flush=True)
            with (out / "progress.jsonl").open("a") as progress:
                progress.write(json.dumps(result, ensure_ascii=False) + "\n")
            return result
    results = await asyncio.gather(*(run(scenario) for scenario in scenarios))
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    lines = ["# Generated next-action evaluation", "", f"Target: `{target.name}`", "",
             "Each second turn below was selected from that session's model-generated actions. Write confirmations were declined.", ""]
    for result in results:
        lines += [f"## {result['scenario']} — {'PASS' if result['passed'] else 'FAIL'}", ""]
        if result.get("error"):
            lines += [result["error"], ""]
        for turn in result.get("turns", []):
            lines += [f"**Request:** {turn['say']}", "", turn["final_text"], "", "Suggested activities:", ""]
            lines += [f"- {action['label']}: {action['prompt']}" for action in turn["next_actions"]]
            lines += ["", f"Time: {turn['latency_s']:.1f}s", ""]
    (out / "summary.md").write_text("\n".join(lines))
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=["local", "remote"], default="local")
    parser.add_argument("--env", default="dev")
    parser.add_argument("--action-index", type=int, default=0)
    parser.add_argument("--scenario", action="append", help="Limit to this scenario; repeat to select several")
    parser.add_argument("--concurrency", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--out", default="build/suggested-actions")
    raise SystemExit(asyncio.run(main(parser.parse_args())))
