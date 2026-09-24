"""Benchmark the briefing plan writer's thinking level: the same opening question, N runs per setting, locally.

    uv run python eval/benchmark_writer.py --project P --namespace demoq0921 --runs 5 --levels medium,low --judge

The opening briefing is the slowest turn in the app and its time is one model call, the plan writer. Each setting
runs in its own process (the agent module reads its configuration at import): PLAN_WRITER_THINKING_LEVEL overrides
the writer's level only, so the coordinator and the three signal readers stay on the environment's level and the
comparison isolates the writer. Runs are sequential, so one run's model call never waits behind another.

Per run: the writer's model-call seconds, the turn's total seconds, the writer's reasoning and output tokens, the
plan's word count, the number of next actions, and with --judge a verdict on whether every fact in the plan is
supported by the evidence the signal readers gathered in that same turn. Writes build/writer-benchmark/<stamp>/
{level}.json and summary.md. Nothing is written to the store; task confirmations are never submitted.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OPENING = "Morning. Just opened up — what should I be on top of first?"
JUDGE_INSTRUCTION = (
    "You review a store opening plan written by an assistant for a store manager. You receive the evidence the "
    "assistant's readers gathered (the inventory, coverage and shrink signal reports the writer was given) and the plan. Decide whether every number, name, "
    "identifier, time and claim in the plan is supported by that evidence, and whether the three decisions are "
    "the most urgent and consequential items the evidence contains. List each unsupported material claim. "
    "decision is 'pass' when there are no unsupported material claims and the priorities are defensible, "
    "'needs_review' when the priorities are defensible but a detail is unsupported, 'fail' when a decision rests "
    "on something the evidence does not say. Return JSON: {decision, unsupported_material_claims: [..], explanation}."
)


WRITER_INPUTS: list[str] = []


def capture_writer_input():
    """Record the instruction the plan writer receives (the three signal reports it must write from).

    The signal readers run inside the briefing tool, so their reports never reach the runner's events; the
    writer's instruction is the one place they appear, and the judge grades the plan against exactly that."""
    from agents.cymbal_store_ops.sub_agents import daily_briefing

    original = daily_briefing.writer_instruction

    def recording(context):
        text = original(context)
        WRITER_INPUTS.append(text)
        return text

    daily_briefing.writer_instruction = recording


def evidence_from(events) -> str:
    """The signal reports the writer was given in this turn, without the writing instructions in front of them."""
    if not WRITER_INPUTS:
        raise RuntimeError("the plan writer's input was not captured; the briefing did not run through the writer")
    text = WRITER_INPUTS.pop()
    marker = "Inventory signals:"
    return text[text.index(marker):] if marker in text else text


def final_text(events) -> str:
    for event in reversed(events or []):
        parts = (event.get("content") or {}).get("parts", [])
        text = "\n".join(p["text"] for p in parts if p.get("text") and not p.get("thought"))
        if text and event.get("author") != "user":
            return text
    return ""


def next_actions(events) -> list:
    actions = []
    for event in events or []:
        delta = (event.get("actions") or {}).get("state_delta") or {}
        if "ui:next_actions" in delta:
            actions = delta["ui:next_actions"] or []
    return actions


MANAGER = {"user:user_id": "U-M014", "user:store_id": "S-014", "user:role": "store_manager", "user:first_name": "Dana"}


async def run_turn(question, project, namespace) -> list[dict]:
    """One local turn as Dana; the events as dicts."""
    os.environ.update({"GOOGLE_CLOUD_PROJECT": project, "WORKSHOP_NAMESPACE": namespace, "STORE_OPS_ENV": "dev",
                       "GOOGLE_GENAI_USE_VERTEXAI": "TRUE", "GOOGLE_CLOUD_LOCATION": "global", "STORE_OPS_PREWARM": "0"})
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    from agents.cymbal_store_ops.agent import create_app

    app = create_app(log_events=False)
    runner = InMemoryRunner(app=app)
    session = await runner.session_service.create_session(app_name=app.name, user_id="benchmark", state=dict(MANAGER))
    message = types.Content(role="user", parts=[types.Part(text=question)])
    return [event.model_dump(mode="json", exclude_none=True)
            async for event in runner.run_async(user_id="benchmark", session_id=session.id, new_message=message)]


def trace_spans(events) -> list[dict]:
    """The agent, model and tool spans the trace plugin writes into the ui:trace:* state keys."""
    spans = {}
    for event in events:
        for key, snapshot in ((event.get("actions") or {}).get("state_delta") or {}).items():
            if key.startswith("ui:trace:"):
                for span in (snapshot.get("spans") if isinstance(snapshot, dict) else snapshot) or []:
                    if span.get("id"):
                        spans[span["id"]] = span
    return list(spans.values())


async def one_run(question, project, namespace):
    started = time.perf_counter()
    events = await run_turn(question, project, namespace)
    total = time.perf_counter() - started
    spans = trace_spans(events)
    writer = [s for s in spans if s.get("kind") == "model" and s.get("agent") == "plan_writer"]
    if len(writer) != 1:
        raise RuntimeError(f"expected one plan_writer model span, found {len(writer)}; the writer did not run, so this is not a briefing turn")
    usage = ((writer[0].get("output") or {}).get("usage") or {})
    text = final_text(events)
    return {
        "total_seconds": round(total, 1),
        "writer_seconds": round((writer[0].get("duration_ms") or 0) / 1000, 1),
        "writer_reasoning_tokens": usage.get("reasoning_token_count"),
        "writer_output_tokens": usage.get("candidates_token_count"),
        "writer_prompt_tokens": usage.get("prompt_token_count"),
        "words": len(text.split()),
        "next_actions": len(next_actions(events)),
        "answer": text,
        "evidence": evidence_from(events),
    }


async def judge(project, runs):
    from google import genai
    from google.genai import types

    client = genai.Client(vertexai=True, project=project, location="global",
                          http_options=types.HttpOptions(timeout=180000, retry_options=types.HttpRetryOptions(attempts=1)))
    for run in runs:
        payload = {"plan": run["answer"], "evidence": run["evidence"]}
        for attempt in (1, 2, 3):
            try:
                response = await client.aio.models.generate_content(
                    model="gemini-3.8-flash", contents=json.dumps(payload, ensure_ascii=False),
                    config=types.GenerateContentConfig(system_instruction=JUDGE_INSTRUCTION, temperature=0,
                                                       response_mime_type="application/json",
                                                       thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MEDIUM)))
                break
            except Exception as error:  # noqa: BLE001 — a judge outage must not discard the measured runs
                if attempt == 3:
                    run["judge"] = {"decision": "judge_error", "unsupported_material_claims": [], "explanation": f"{type(error).__name__}: {error}"[:300]}
                    print(f"judge failed three times for one run and is recorded as judge_error: {error}", flush=True)
                    break
                await asyncio.sleep(20 * attempt)
        else:
            continue
        if "judge" in run:
            continue
        verdict = json.loads(response.text)
        if verdict.get("decision") not in {"pass", "needs_review", "fail"}:
            raise ValueError(f"judge returned an unknown decision: {verdict!r}")
        run["judge"] = verdict


async def run_level(args):
    if args.level != "inherit":
        os.environ["PLAN_WRITER_THINKING_LEVEL"] = args.level
    capture_writer_input()
    runs = []
    for index in range(args.runs):
        run = await one_run(args.question, args.project, args.namespace)
        print(f"{args.level:8} run {index + 1}: writer {run['writer_seconds']} s of {run['total_seconds']} s, "
              f"reasoning tokens {run['writer_reasoning_tokens']}, {run['words']} words, {run['next_actions']} chips", flush=True)
        runs.append(run)
        # the measurements are saved as they land, so a judge outage afterwards cannot lose them
        Path(args.out).write_text(json.dumps({"level": args.level, "question": args.question, "runs": runs}, ensure_ascii=False, indent=2))
    if args.judge:
        await judge(args.project, runs)
        for index, run in enumerate(runs, 1):
            print(f"{args.level:8} run {index}: judge {run['judge']['decision']} — {run['judge']['explanation'][:160]}", flush=True)
    Path(args.out).write_text(json.dumps({"level": args.level, "question": args.question, "runs": runs}, ensure_ascii=False, indent=2))


def stat(values):
    values = [v for v in values if v is not None]
    return f"{statistics.median(values):.1f} (min {min(values):.1f}, max {max(values):.1f})" if values else "n/a"


def summarize(folder: Path, levels: list[str]) -> str:
    lines = ["# Plan writer thinking-level benchmark", "",
             f"Question: {OPENING!r}. Runs are sequential, local, one process per setting; `inherit` is the environment's",
             "`thinking_level` (medium in dev). Writer seconds are the plan writer's single model call; total is the whole turn.", "",
             "| writer level | runs | writer s median (min, max) | total s median (min, max) | reasoning tokens median | words median | chips | judge |",
             "|---|---|---|---|---|---|---|---|"]
    for level in levels:
        data = json.loads((folder / f"{level}.json").read_text())
        runs = data["runs"]
        verdicts = [r.get("judge", {}).get("decision") for r in runs]
        judged = ", ".join(f"{v}×{verdicts.count(v)}" for v in ("pass", "needs_review", "fail", "judge_error") if verdicts.count(v)) or "not judged"
        lines.append(f"| {level} | {len(runs)} | {stat([r['writer_seconds'] for r in runs])} | {stat([r['total_seconds'] for r in runs])} | "
                     f"{stat([r['writer_reasoning_tokens'] for r in runs])} | {stat([r['words'] for r in runs])} | "
                     f"{stat([r['next_actions'] for r in runs])} | {judged} |")
    lines += ["", "## Unsupported claims the judge found", ""]
    for level in levels:
        for index, run in enumerate(json.loads((folder / f"{level}.json").read_text())["runs"], 1):
            claims = run.get("judge", {}).get("unsupported_material_claims") or []
            for claim in claims:
                lines.append(f"- {level} run {index}: {claim}")
    if lines[-1] == "":
        lines.append("- none")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    parser.add_argument("--namespace", default="demoq0921", help="a namespace with clean evaluation data, never the demo")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--levels", default="inherit,low", help="comma-separated writer levels; inherit = the environment's")
    parser.add_argument("--question", default=OPENING)
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--level", help="(internal) run one level in this process")
    args = parser.parse_args()
    if not args.project:
        parser.error("--project is required (or set GOOGLE_CLOUD_PROJECT)")
    if args.namespace == "demo":
        parser.error("Use an evaluation namespace, not the demo, so the benchmark never touches the demo's records")
    if args.level:
        asyncio.run(run_level(args))
        return 0
    folder = args.out or ROOT / "build" / "writer-benchmark" / time.strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    levels = [level.strip() for level in args.levels.split(",") if level.strip()]
    for level in levels:
        command = [sys.executable, str(Path(__file__).resolve()), "--level", level, "--project", args.project, "--namespace", args.namespace,
                   "--runs", str(args.runs), "--question", args.question, "--out", str(folder / f"{level}.json")] + (["--judge"] if args.judge else [])
        completed = subprocess.run(command, cwd=ROOT, check=False)
        if completed.returncode != 0:
            raise SystemExit(f"level {level} failed (exit {completed.returncode}); see the output above")
    summary = summarize(folder, levels)
    (folder / "summary.md").write_text(summary)
    print(summary)
    print(f"written to {folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
