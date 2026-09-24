"""Custom evaluation metric for quickstart 07, registered in eval/test_config.json (`custom_metrics`).

discrepancy_invariant — the checked proof has exactly the expected discrepancies. For a case whose golden carries an
expected `compare_promo_proof` response, the actual run scores 1.0 only when:
  * `compare_promo_proof` ran and its response lists exactly the golden's (product_id, issue) pairs, no more and no
    fewer, with `discrepancy_count` equal to that number (so the model extracted the proof correctly: the comparison
    itself is code);
  * the final report names every expected product id (so the checker relayed all of them).
Everything else scores 0.0. A case without an expected `compare_promo_proof` response is not a proofing case and
passes. Deterministic: no model, no judge.
"""
from __future__ import annotations

import re

from google.adk.evaluation.eval_case import Invocation, get_all_tool_responses
from google.adk.evaluation.evaluator import EvalStatus, EvaluationResult, PerInvocationResult

TOOL = "compare_promo_proof"


def _response(inv: Invocation | None) -> dict | None:
    """The last compare_promo_proof response recorded in an invocation, or None."""
    found = [r.response for r in get_all_tool_responses(inv.intermediate_data) if r.name == TOOL] if inv else []
    return dict(found[-1]) if found else None


def _pairs(response: dict) -> set[tuple[str | None, str]]:
    return {(row.get("product_id"), row.get("issue")) for row in response.get("rows") or []}


def _final_text(inv: Invocation) -> str:
    return "".join(p.text or "" for p in (inv.final_response.parts if inv.final_response else []) or [])


def score(actual: Invocation, expected: Invocation | None) -> float:
    golden = _response(expected)
    if golden is None:
        return 1.0
    got = _response(actual)
    if got is None or got.get("status") != "SUCCESS":
        return 0.0
    want = _pairs(golden)
    if _pairs(got) != want or int(got.get("discrepancy_count", -1)) != len(want):
        return 0.0
    text = _final_text(actual)
    ids = {pid for pid, _ in want if pid}
    return 1.0 if all(re.search(rf"\b{re.escape(pid)}\b", text) for pid in ids) else 0.0


def discrepancy_invariant(eval_metric, actual_invocations: list[Invocation],
                          expected_invocations: list[Invocation] | None = None,
                          conversation_scenario=None) -> EvaluationResult:
    """ADK custom-metric signature: (eval_metric, actual, expected, conversation_scenario)."""
    pairs = list(zip(actual_invocations, expected_invocations or [None] * len(actual_invocations), strict=False))
    per = []
    for actual, expected in pairs:
        s = score(actual, expected)
        per.append(PerInvocationResult(actual_invocation=actual, expected_invocation=expected, score=s,
                                       eval_status=EvalStatus.PASSED if s >= 1.0 else EvalStatus.FAILED))
    overall = sum(p.score for p in per) / len(per) if per else 0.0
    return EvaluationResult(overall_score=overall, per_invocation_results=per,
                            overall_eval_status=EvalStatus.PASSED if overall >= 1.0 else EvalStatus.FAILED)
