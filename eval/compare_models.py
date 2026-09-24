"""Model-upgrade regression: run the evaluation gate once per candidate model and compare the scores.

    uv run python eval/compare_models.py --models gemini-3.8-flash,gemini-2.5-pro

Each model runs in its own process (the agent module builds its App at import time, so the model has to be
fixed before the import). Every run writes the per-invocation results the ADK evaluator produces
(`build/model_regression/<model>.csv`); the parent folds them into one table, case x metric x model, plus a
per-model summary (gate result, failed cases, wall time), written to `build/model_regression.md`.

A model that fails the gate is reported, not hidden: the table shows the scores and the summary says FAILED.
A model that cannot be reached (404, quota) stops the comparison with the error, because a missing column would
misrepresent the comparison.
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BUILD = ROOT / "build" / "model_regression"
DEFAULT_EVALSET = ROOT / "eval" / "evalsets" / "gate.evalset.json"
AGENT_MODULE = "agents.cymbal_store_ops.agent"

EXIT_GATE_FAILED = 2


def run_one(model: str, evalset: Path, csv_path: Path, num_runs: int) -> int:
    """Child process: evaluate the agent with one model; exit 0 (passed), 2 (threshold breached), 1 (error)."""
    import asyncio

    os.environ["MODEL"] = model
    os.environ["STORE_OPS_FAULT"] = "none"
    from google.adk.evaluation.agent_evaluator import AgentEvaluator

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if csv_path.exists():
        csv_path.unlink()  # the evaluator appends
    try:
        asyncio.run(AgentEvaluator.evaluate(
            agent_module=AGENT_MODULE,
            eval_dataset_file_path_or_dir=str(evalset),
            num_runs=num_runs,
            print_detailed_results=False,
            output_file=str(csv_path),
        ))
    except AssertionError as failure:  # thresholds breached: the CSV still holds every score
        print(f"[{model}] gate FAILED: {str(failure)[:300]}")
        return EXIT_GATE_FAILED
    print(f"[{model}] gate passed")
    return 0


def probe_models(models: list[str], client=None) -> None:
    """One tiny call per model before any gate runs, so a model this project cannot call fails here with the API's
    own message and the fix, not seven minutes later as "the CSV holds no scores" (pass 4, 2026-09-17: the default
    second model was 404 in the sandbox on global; only gemini-3.8-flash and gemini-2.5-pro answered)."""
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    if client is None:
        from google import genai
        client = genai.Client(vertexai=True, project=project or None, location=location)
    for model in models:
        try:
            client.models.generate_content(model=model, contents="Say ok.", config={"max_output_tokens": 5})
        except Exception as e:  # noqa: BLE001 — every failure is the same finding: this project cannot call the model here
            raise SystemExit(f"{model} cannot be called in {location} for project {project or '<unset>'}: "
                             f"{str(e)[:160]}\n  Fix: pick two models your project can call, e.g. "
                             f"uv run python eval/compare_models.py --models gemini-3.8-flash,gemini-2.5-pro") from None


def load_scores(csv_path: Path) -> dict[tuple[str, str], list[float]]:
    """(eval_id, metric_name) -> scores across runs, from the evaluator's CSV."""
    scores: dict[tuple[str, str], list[float]] = defaultdict(list)
    with csv_path.open(newline="") as f:
        for row in csv.DictReader(f):
            raw = (row.get("score") or "").strip()
            if raw == "":
                continue
            scores[(row["eval_id"], row["metric_name"])].append(float(raw))
    if not scores:
        raise RuntimeError(f"{csv_path} holds no scores; the evaluator wrote nothing usable")
    return dict(scores)


def aggregate(per_model: dict[str, dict[tuple[str, str], list[float]]]) -> dict[tuple[str, str], dict[str, float]]:
    """(eval_id, metric) -> {model: mean score}; a model without the pair is absent (rendered as a dash)."""
    table: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    for model, scores in per_model.items():
        for key, values in scores.items():
            table[key][model] = statistics.fmean(values)
    return dict(sorted(table.items()))


def render_markdown(table: dict[tuple[str, str], dict[str, float]], summary: dict[str, dict], models: list[str],
                    evalset: str, num_runs: int) -> str:
    lines = [f"# Model-upgrade regression: `{evalset}` x {num_runs} run(s)", ""]
    lines += ["| Model | Gate | Cases below threshold | Wall time |", "|---|---|---|---|"]
    for m in models:
        s = summary[m]
        lines.append(f"| `{m}` | {'PASSED' if s['passed'] else 'FAILED'} | {s['failed_cases']} | {s['seconds']:.0f} s |")
    lines += ["", "| Case | Metric | " + " | ".join(f"`{m}`" for m in models) + " |",
              "|---|---|" + "---|" * len(models)]
    for (eval_id, metric), by_model in table.items():
        cells = [f"{by_model[m]:.2f}" if m in by_model else "—" for m in models]
        lines.append(f"| {eval_id} | {metric} | " + " | ".join(cells) + " |")
    lines += ["", "Scores are the mean over runs; the gate uses the thresholds in `eval/evalsets/test_config.json`.",
              "A lower score on the candidate is a regression to investigate before switching the model pin."]
    return "\n".join(lines) + "\n"


def failed_cases(scores: dict[tuple[str, str], list[float]], thresholds: dict[str, float]) -> int:
    cases = set()
    for (eval_id, metric), values in scores.items():
        t = thresholds.get(metric)
        if t is not None and statistics.fmean(values) < t:
            cases.add(eval_id)
    return len(cases)


def load_thresholds(evalset: Path) -> dict[str, float]:
    import json

    cfg = json.loads((evalset.parent / "test_config.json").read_text())
    out: dict[str, float] = {}
    for name, spec in cfg.get("criteria", {}).items():
        out[name] = float(spec["threshold"] if isinstance(spec, dict) else spec)
    return out


def main() -> int:
    from agents.cymbal_store_ops.preflight import require_sign_in

    require_sign_in()   # an expired sign-in stops here, in words, not as a stack trace later
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default="gemini-3.8-flash,gemini-2.5-pro", help="comma-separated candidate model ids")
    ap.add_argument("--evalset", default=str(DEFAULT_EVALSET))
    ap.add_argument("--num-runs", type=int, default=1)
    ap.add_argument("--out", default=str(ROOT / "build" / "model_regression.md"))
    ap.add_argument("--one", metavar="MODEL", help="(internal) evaluate one model in this process")
    ap.add_argument("--csv", help="(internal) CSV path for --one")
    a = ap.parse_args()
    evalset = Path(a.evalset)
    if a.one:
        return run_one(a.one, evalset, Path(a.csv), a.num_runs)

    from eval.preconditions import assert_fixture_state

    assert_fixture_state()   # both models must read the fixture, not what a lab step wrote
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    if len(models) < 2:
        raise SystemExit("--models needs at least two model ids to compare")
    probe_models(models)
    thresholds = load_thresholds(evalset)
    per_model: dict[str, dict[tuple[str, str], list[float]]] = {}
    summary: dict[str, dict] = {}
    for model in models:
        csv_path = BUILD / f"{model}.csv"
        t0 = time.time()
        proc = subprocess.run([sys.executable, __file__, "--one", model, "--evalset", str(evalset),
                               "--csv", str(csv_path), "--num-runs", str(a.num_runs)], cwd=ROOT)
        seconds = time.time() - t0
        if proc.returncode not in (0, EXIT_GATE_FAILED):
            raise SystemExit(f"{model}: evaluation errored (exit {proc.returncode}); fix that before comparing")
        per_model[model] = load_scores(csv_path)
        summary[model] = {"passed": proc.returncode == 0, "seconds": seconds,
                          "failed_cases": failed_cases(per_model[model], thresholds)}
    table = aggregate(per_model)
    md = render_markdown(table, summary, models, evalset.name, a.num_runs)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)
    print(md)
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
