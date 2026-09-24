"""The evaluation gate. `adk eval` never fails the build; this test does.

    uv run pytest tests/eval -q -k test_golden_gate_passes                               # the gate: gate.evalset.json, 2 runs per case, thresholds from test_config.json
    STORE_OPS_FAULT=stale_stock uv run pytest tests/eval -q -k test_golden_gate_passes       # the same gate with a stale feed: runs only the cases that read it, must FAIL
    uv run pytest tests/eval -q -k test_fault_switch_breaks_the_gate                        # proves both faults still trip their invariant (CI runs it next to the gate)
"""
from __future__ import annotations

import os
import sys
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
EVALSETS = ROOT / "eval" / "evalsets"
GATE = EVALSETS / "gate.evalset.json"
NUM_RUNS = int(os.environ.get("EVAL_NUM_RUNS", "2"))


async def _evaluate(evalset: Path, *, missing_pickup_feed=False) -> None:
    from google.adk.evaluation.agent_evaluator import AgentEvaluator
    from google.adk.evaluation.local_eval_set_results_manager import LocalEvalSetResultsManager

    run_dir = Path(os.environ.get("EVAL_RESULTS_DIR", ROOT / "build/eval_runs")) / (
        f"{evalset.stem}-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}")
    run_dir.mkdir(parents=True, exist_ok=False)
    print(f"Full evaluation evidence: {run_dir}", flush=True)
    from eval.pickup_fault import missing_pending_feed

    with missing_pending_feed() if missing_pickup_feed else nullcontext():
        return await AgentEvaluator.evaluate(
            agent_module="agents.cymbal_store_ops.agent",
            eval_dataset_file_path_or_dir=str(evalset),
            num_runs=NUM_RUNS,
            print_detailed_results=True,
            app_name="cymbal_store_ops",
            eval_set_results_manager=LocalEvalSetResultsManager(str(run_dir)),
            output_file=str(run_dir / "metrics.csv"),
        )


# fault -> (the small evalset whose cases read the faulty feed, the metric that must catch it)
FAULT_EVALSETS = {
    "stale_stock": ("stock_invariant.evalset.json", "stock_invariant"),
    "stale_backlog": ("pickup_fault/pickup_counts.evalset.json", "pickup_counts_invariant"),
}


@pytest.mark.asyncio
async def test_golden_gate_passes():
    """The gate. With STORE_OPS_FAULT set it evaluates only the cases that read the faulty feed, and it fails:
    that red run is the 'break it' step. The full gate fails the same way, just slower."""
    assert GATE.exists(), "run: uv run python eval/build_eval_set.py"
    fault = os.environ.get("STORE_OPS_FAULT", "none") or "none"
    if fault == "none":
        await _evaluate(GATE)
        return
    if fault not in FAULT_EVALSETS:
        raise AssertionError(f"STORE_OPS_FAULT={fault!r}: expected one of {sorted(FAULT_EVALSETS)}")
    await _evaluate(EVALSETS / FAULT_EVALSETS[fault][0], missing_pickup_feed=fault == "stale_backlog")


@pytest.mark.asyncio
@pytest.mark.parametrize("fault, evalset, metric", [(f, e, m) for f, (e, m) in FAULT_EVALSETS.items()])
async def test_fault_switch_breaks_the_gate(monkeypatch, fault, evalset, metric):
    """Deterministic 'break it': each injected fault must trip its invariant metric, and only that way."""
    from agents.cymbal_store_ops import config

    if fault == "stale_backlog":
        monkeypatch.setenv("STORE_OPS_FAULT", "none")
        config.load_env_config.cache_clear()
        await _evaluate(EVALSETS / evalset)
    monkeypatch.setenv("STORE_OPS_FAULT", fault)
    config.load_env_config.cache_clear()
    with pytest.raises(AssertionError) as failure:
        await _evaluate(EVALSETS / evalset, missing_pickup_feed=fault == "stale_backlog")
    from eval.fault_assertions import fault_was_detected

    message = str(failure.value)
    assert fault_was_detected(message, metric), message[:500]
    config.load_env_config.cache_clear()
