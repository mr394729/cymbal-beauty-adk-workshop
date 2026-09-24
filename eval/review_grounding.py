"""Review saved ADK invocations against their actual tool evidence, without rerunning the agent.

Example:
  uv run python eval/review_grounding.py --input build/eval_runs/<run>/cymbal_store_ops/.adk/eval_history/<result>.evalset_result.json \
      --case osa_explanation --case coverage_recommendation --out build/grounding-review

This invokes ADK's hallucinations_v1 judge, including intermediate natural-language answers.
It is a separate diagnostic until calibrated against reviewed positive and negative examples;
existing gate thresholds are unchanged. No store tools, writes or fresh agent turns are run.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from google.adk.evaluation.eval_result import EvalSetResult  # noqa: E402


def saved_cases(path: Path, case_ids: set[str]):
    result = EvalSetResult.model_validate_json(path.read_text())
    available = {case.eval_id for case in result.eval_case_results}
    if case_ids - available:
        raise ValueError(f"Unknown cases: {sorted(case_ids - available)}")
    selected = [case for case in result.eval_case_results if not case_ids or case.eval_id in case_ids]
    for case in selected:
        if not case.eval_metric_result_per_invocation:
            raise ValueError(f"No saved invocation for {case.eval_id}/{case.session_id}")
        for turn in case.eval_metric_result_per_invocation:
            if turn.actual_invocation is None or turn.actual_invocation.intermediate_data is None:
                raise ValueError(f"Missing actual evidence for {case.eval_id}/{case.session_id}")
    return selected


async def review(args):
    from google.adk.evaluation.eval_metrics import (
        EvalMetric,
        HallucinationsCriterion,
        JudgeModelOptions,
    )
    from google.adk.evaluation.hallucinations_v1 import HallucinationsV1Evaluator

    from agents.cymbal_store_ops.preflight import require_sign_in

    cases = saved_cases(args.input, set(args.case))
    require_sign_in()
    args.out.mkdir(parents=True, exist_ok=False)
    metric = EvalMetric(metric_name="hallucinations_v1", criterion=HallucinationsCriterion(
        threshold=1.0, judge_model_options=JudgeModelOptions(judge_model=args.model, num_samples=args.samples),
        evaluate_intermediate_nl_responses=True))
    evaluator = HallucinationsV1Evaluator(metric)
    results = []
    for index, case in enumerate(cases, 1):
        invocations = [turn.actual_invocation for turn in case.eval_metric_result_per_invocation]
        started = time.perf_counter()
        scored = await evaluator.evaluate_invocations(actual_invocations=invocations)
        record = {"eval_id": case.eval_id, "session_id": case.session_id,
                  "seconds": round(time.perf_counter() - started, 3),
                  "result": scored.model_dump(mode="json")}
        (args.out / f"{index:02d}-{case.eval_id}.json").write_text(json.dumps(record, indent=2) + "\n")
        results.append({key: record[key] for key in ("eval_id", "session_id", "seconds")} |
                       {"score": scored.overall_score, "status": scored.overall_eval_status.name})
        print(json.dumps(results[-1]), flush=True)
    (args.out / "summary.json").write_text(json.dumps({"source": str(args.input),
        "metric": metric.model_dump(mode="json"), "cases": results}, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default="gemini-3.8-flash")
    parser.add_argument("--samples", type=int, choices=range(1, 4), default=1)
    asyncio.run(review(parser.parse_args()))


if __name__ == "__main__":
    main()
