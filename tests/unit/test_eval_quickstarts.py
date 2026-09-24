"""The quickstart eval runner: failing metrics named from the evaluator's summary lines; uploads preloaded per session."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("eval_quickstarts", ROOT / "scripts" / "eval_quickstarts.py")
eq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eq)

STDOUT = """
Summary: `EvalStatus.PASSED` for Metric: `tool_trajectory_avg_score`. Expected threshold: `1.0`, actual value: `1.0`.
+----+ a detail table +----+
Summary: `EvalStatus.FAILED` for Metric: `response_match_score`. Expected threshold: `0.3`, actual value: `0.19047619047619047`.
Summary: `EvalStatus.NOT_EVALUATED` for Metric: `final_response_match_v2`. Expected threshold: `0.8`, actual value: `None`.
"""


def test_failing_metrics_names_each_metric_with_score_and_threshold():
    assert eq.failing_metrics(STDOUT) == "response_match_score 0.19 < 0.3; final_response_match_v2 not evaluated"
    assert eq.failing_metrics("Summary: `EvalStatus.PASSED` for Metric: `x`. Expected threshold: `1.0`, actual value: `1.0`.") == ""


def test_inference_failures_are_recognised():
    line = "Inference failed for eval case `promo_proof` with error 1 validation error for Schema"
    assert eq.INFERENCE_FAILED.findall(line) == [("promo_proof", "1 validation error for Schema")]


def test_artifacts_are_saved_into_each_pinned_session():
    evalset = ROOT / "quickstarts" / "07-document-extraction-agent" / "eval" / "document_extraction_agent.evalset.json"
    service = eq._artifact_service(evalset)
    names = asyncio.run(service.list_artifact_keys(app_name="document_extraction_agent", user_id="eval-user",
                                                   session_id="promo-proof-golden"))
    assert names == ["promo_proof_S-014_2026W40.pdf"]


def test_no_artifacts_folder_means_no_service():
    evalset = ROOT / "quickstarts" / "01-hello-tool-agent" / "eval" / "hello_tool_agent.evalset.json"
    assert eq._artifact_service(evalset) is None


def test_artifacts_without_a_pinned_session_are_refused(tmp_path: Path):
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "proof.pdf").write_bytes(b"%PDF-1.4\n")
    source = ROOT / "quickstarts" / "01-hello-tool-agent" / "eval" / "hello_tool_agent.evalset.json"
    target = tmp_path / "x.evalset.json"
    target.write_text(source.read_text())
    with pytest.raises(RuntimeError, match="session_id"):
        eq._artifact_service(target)
