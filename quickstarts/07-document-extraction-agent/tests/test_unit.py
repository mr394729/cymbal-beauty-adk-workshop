"""Pipeline shape, schema bounds and the deterministic cross-check, with no model."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from google.adk.agents import LoopAgent, SequentialAgent
from google.adk.plugins.save_files_as_artifacts_plugin import SaveFilesAsArtifactsPlugin
from pydantic import ValidationError

HERE = Path(__file__).resolve().parents[1]
# What is printed on eval/artifacts/promo_proof_S-014_2026W40.pdf (quickstarts/_scripts/make_promo_proof.py).
PRINTED = {"store_id": "S-014", "week": "2026-W40", "confidence": 0.95, "lines": [
    {"line": 1, "product_id": "P-0101", "product_name": "Lumière Hydra Cream", "sign_type": "shelf talker", "promo_price_usd": 24.99, "start_date": "2026-10-04", "end_date": "2026-10-10"},
    {"line": 2, "product_id": "P-0420", "product_name": "Noir Velvet Eau de Parfum", "sign_type": "locked case card", "promo_price_usd": 79.0, "start_date": "2026-10-04", "end_date": "2026-10-10"},
    {"line": 3, "product_id": "P-0141", "product_name": "Hydra Moisturizer", "sign_type": "end cap sign", "promo_price_usd": 9.99, "start_date": "2026-10-04", "end_date": "2026-10-17"},
    {"line": 4, "product_id": "P-0333", "product_name": "Glow Body Wash", "sign_type": "shelf talker", "promo_price_usd": 25.0, "start_date": "2026-10-04", "end_date": "2026-10-10"},
    {"line": 5, "product_id": "P-0231", "product_name": "Lift Hair Mask", "sign_type": "shelf talker", "promo_price_usd": 11.0, "start_date": "2026-10-04", "end_date": "2026-10-10"},
]}


class FakeToolContext:
    def __init__(self, state: dict) -> None:
        self.state = state


def test_pipeline_shape(quickstart):
    root = quickstart.root_agent
    assert isinstance(root, SequentialAgent) and [a.name for a in root.sub_agents] == ["extract_and_review", "checker"]
    loop = root.sub_agents[0]
    assert isinstance(loop, LoopAgent) and loop.max_iterations == 2
    assert [a.name for a in loop.sub_agents] == ["extractor", "critic"]
    assert loop.sub_agents[0].output_schema is quickstart.PromoProof and loop.sub_agents[0].output_key == "proof"
    assert any(isinstance(p, SaveFilesAsArtifactsPlugin) for p in quickstart.app.plugins)


def test_schema_bounds(quickstart):
    assert quickstart.PromoProof.model_validate(PRINTED).needs_human_review is False
    with pytest.raises(ValidationError):
        quickstart.PromoProof.model_validate({**PRINTED, "confidence": 1.4})


def test_the_printed_proof_has_exactly_three_discrepancies(quickstart):
    result = quickstart.compare_promo_proof(FakeToolContext({"proof": PRINTED}))
    assert result["status"] == "SUCCESS" and result["discrepancy_count"] == 3
    assert [(r["line"], r["product_id"], r["issue"]) for r in result["rows"]] == [
        (1, "P-0101", "price_mismatch"), (3, "P-0141", "end_date_mismatch"), (4, "P-0333", "not_on_promotion")]


def test_a_correct_proof_matches_and_a_missing_sign_is_caught(quickstart):
    plan = json.loads(quickstart.PLAN.read_text())
    good = {"week": plan["week"], "lines": [{"line": i + 1, **p} for i, p in enumerate(plan["promotions"])]}
    assert quickstart.compare(good, plan) == []
    partial = {**good, "lines": good["lines"][1:]}
    assert [r["issue"] for r in quickstart.compare(partial, plan)] == ["missing_sign"]


def test_no_proof_in_state_is_an_error(quickstart):
    assert quickstart.compare_promo_proof(FakeToolContext({}))["status"] == "ERROR"


def test_checked_in_proof_matches_its_generator():
    script = HERE.parent / "_scripts" / "make_promo_proof.py"
    assert subprocess.run([sys.executable, str(script), "--check"], capture_output=True).returncode == 0


# ---- the discrepancy_invariant eval metric (metrics.py) ------------------------------------------------------------
def _golden():
    from google.adk.evaluation.eval_set import EvalSet

    es = EvalSet.model_validate_json((HERE / "eval" / "document_extraction_agent.evalset.json").read_text())
    return es.eval_cases[0].conversation[0]


def _recorded_run(tool_response: dict | None, report: str):
    """An actual invocation built the way the evaluator records a run: from ADK events."""
    from google.adk.evaluation.evaluation_generator import EvaluationGenerator
    from google.adk.events import Event
    from google.genai import types

    events = [Event(invocation_id="inv", author="user",
                    content=types.Content(role="user", parts=[types.Part(text="Check the proof I attached.")]))]
    if tool_response is not None:
        events += [
            Event(invocation_id="inv", author="checker", content=types.Content(role="model", parts=[types.Part(
                function_call=types.FunctionCall(id="c1", name="compare_promo_proof", args={}))])),
            Event(invocation_id="inv", author="checker", content=types.Content(role="user", parts=[types.Part(
                function_response=types.FunctionResponse(id="c1", name="compare_promo_proof", response=tool_response))])),
        ]
    events.append(Event(invocation_id="inv", author="checker",
                        content=types.Content(role="model", parts=[types.Part(text=report)])))
    (invocation,) = EvaluationGenerator.convert_events_to_eval_invocations(events)
    return invocation


REPORT = ("3 discrepancies. Line 1 P-0101: proof $24.99, plan $22.99. Line 3 P-0141: proof ends 2026-10-17, plan "
          "2026-10-10. Line 4 P-0333: not on promotion this week.")


def _metric(quickstart_module_name: str = "07-document-extraction-agent.metrics"):
    import importlib

    return importlib.import_module(quickstart_module_name)


def test_golden_expects_exactly_what_the_comparison_returns_for_the_printed_proof(quickstart):
    from google.adk.evaluation.eval_case import get_all_tool_responses

    (expected,) = [r.response for r in get_all_tool_responses(_golden().intermediate_data) if r.name == "compare_promo_proof"]
    assert expected == quickstart.compare_promo_proof(FakeToolContext({"proof": PRINTED}))


def test_three_discrepancies_reported_pass(quickstart):
    run = _recorded_run(quickstart.compare_promo_proof(FakeToolContext({"proof": PRINTED})), REPORT)
    result = _metric().discrepancy_invariant(None, [run], [_golden()])
    assert result.overall_score == 1.0 and result.overall_eval_status.name == "PASSED"


def test_a_two_discrepancy_response_fails(quickstart):
    """The extractor skipped line 4, so P-0333 is never compared: the comparison finds only two discrepancies."""
    proof = json.loads(json.dumps(PRINTED))
    del proof["lines"][3]
    two = quickstart.compare_promo_proof(FakeToolContext({"proof": proof}))
    assert two["discrepancy_count"] == 2
    result = _metric().discrepancy_invariant(None, [_recorded_run(two, REPORT)], [_golden()])
    assert result.overall_score == 0.0 and result.overall_eval_status.name == "FAILED"


def test_an_extra_discrepancy_a_missing_product_in_the_report_or_no_comparison_fails(quickstart):
    m, golden = _metric(), _golden()
    good = quickstart.compare_promo_proof(FakeToolContext({"proof": PRINTED}))
    extra = {**good, "discrepancy_count": 4, "rows": good["rows"] + [{"line": None, "product_id": "P-0050", "issue": "missing_sign"}]}
    assert m.discrepancy_invariant(None, [_recorded_run(extra, REPORT)], [golden]).overall_score == 0.0
    assert m.discrepancy_invariant(None, [_recorded_run(good, REPORT.replace("P-0333", "Glow Body Wash"))], [golden]).overall_score == 0.0
    assert m.discrepancy_invariant(None, [_recorded_run(None, REPORT)], [golden]).overall_score == 0.0


def test_metric_is_registered_in_the_test_config():
    import importlib

    from google.adk.evaluation.eval_config import EvalConfig

    cfg = EvalConfig.model_validate(json.loads((HERE / "eval" / "test_config.json").read_text()))
    assert cfg.criteria["discrepancy_invariant"] == 1.0
    module, _, fn = cfg.custom_metrics["discrepancy_invariant"].code_config.name.rpartition(".")
    assert callable(getattr(importlib.import_module(module), fn))


def test_tree_refuses_without_an_attached_proof(quickstart):
    """No artifact in the session: the root returns the instruction and no agent runs (the extractor looped forever live)."""
    import asyncio

    class Ctx:
        def __init__(self, names):
            self._names = names

        async def list_artifacts(self):
            return self._names

    assert quickstart.root_agent.before_agent_callback is quickstart.require_a_proof
    skip = asyncio.run(quickstart.require_a_proof(Ctx([])))
    assert skip is not None and "Upload the proof PDF" in skip.parts[0].text
    assert asyncio.run(quickstart.require_a_proof(Ctx(["promo_proof_S-014_2026W40.pdf"]))) is None
