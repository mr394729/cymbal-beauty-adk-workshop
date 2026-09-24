"""Independent breadth oracles, recorded evidence, timeout and no-false-pass behavior."""
import asyncio
import json

import pytest

from eval.broad_scenarios import IDENTITIES, build_dataset, load_data
from eval.run_broad import clean_event, percentile, run_case, summarize, trace_metrics


@pytest.fixture(scope="module")
def source_snapshot(tmp_path_factory):
    """Each clean checkout builds its own deterministic evaluation evidence."""
    from data.generate import generate_all

    folder = tmp_path_factory.mktemp("breadth-source")
    for name, rows in generate_all().items():
        (folder / f"{name}.ndjson").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        )
    return folder


def test_fifty_distinct_questions_with_raw_data_ground_truth_and_no_tool_paths(source_snapshot):
    dataset = build_dataset(source_snapshot)
    cases = dataset["cases"]
    assert len(cases) == 50
    assert len({c["turns"][0]["question"] for c in cases}) == 50
    assert sum(len(c["turns"]) for c in cases) == 53
    assert len({c["domain"] for c in cases}) >= 12
    assert len(cases[-1]["turns"]) == 4
    assert cases[-1]["turns"][1]["question"] == "give me a breakdown of our stock in the store"
    assert cases[-1]["turns"][3]["question"] == "No I want complete store inventory."
    assert all(t["oracle"] and t["criteria"] for c in cases for t in c["turns"])
    assert "tools_all" not in json.dumps(cases) and "tools_any" not in json.dumps(cases)
    rows = [json.loads(line) for line in (source_snapshot / "store_inventory.ndjson").read_text().splitlines()]
    store = [r for r in rows if r["store_id"] == "S-014"]
    totals = cases[5]["turns"][0]["oracle"][0]["value"]
    assert totals["sku_count"] == len(store) == 600
    assert totals["on_hand_units"] == sum(r["on_hand"] for r in store)
    assert totals["on_hand_units"] == totals["shelf_units"] + totals["backroom_units"]
    assert set(dataset["source_sha256"]) >= {"products", "store_inventory", "bopis_orders", "store_tasks"}
    assert build_dataset(source_snapshot)["cases"] == cases
    assert build_dataset(source_snapshot, seed=99)["cases"][0]["turns"][0]["question"] != cases[0]["turns"][0]["question"]


def test_oracle_recomputes_stock_totals_when_raw_snapshot_changes(monkeypatch, source_snapshot):
    data, hashes = load_data(source_snapshot)
    for row in data["store_inventory"]:
        if row["store_id"] == "S-014" and row["product_id"] == "P-0001":
            row["on_hand"] += 17
            row["backroom_qty"] += 17
    baseline = build_dataset(source_snapshot)["cases"][5]["turns"][0]["oracle"][0]["value"]
    monkeypatch.setattr("eval.broad_scenarios.load_data", lambda _: (data, hashes))
    changed = build_dataset(source_snapshot)["cases"][5]["turns"][0]["oracle"][0]["value"]
    assert changed["on_hand_units"] == baseline["on_hand_units"] + 17
    assert changed["backroom_units"] == baseline["backroom_units"] + 17
    assert changed["shelf_units"] == baseline["shelf_units"]


def test_trace_usage_deduplicates_snapshots_and_does_not_invent_reasoning_counts():
    span = {"id": "one", "kind": "model", "agent": "root", "name": "model", "status": "ok", "duration_ms": 123,
            "output": {"usage": {"prompt_token_count": 50, "candidates_token_count": 10, "total_token_count": 80}}}
    event = {"actions": {"state_delta": {"ui:trace:root": {"spans": [span]}}}}
    result = trace_metrics([event, event])
    assert result["model_calls"] == 1
    assert result["model_usage_sum"]["total_token_count"] == 80
    assert result["model_usage_sum"]["reasoning_token_count"] is None
    assert result["models"][0]["duration_ms"] == 123


def test_recorded_events_drop_reasoning_without_mutating_operational_input():
    event = {"content": {"parts": [{"text": "private", "thought": True},
                                  {"text": "public", "thought_signature": "opaque"}]}}
    cleaned = clean_event(event)
    assert cleaned["content"]["parts"] == [{"text": "public"}]
    assert len(event["content"]["parts"]) == 2


class Target:
    def __init__(self, *, confirmation=False, timeout=False):
        self.payloads = []
        self.confirmation, self.timeout = confirmation, timeout

    async def create_session(self, user_id, state):
        return "test-session"

    async def state(self, *args):
        return IDENTITIES["manager"]

    async def stream(self, user, sid, payload, invocation):
        self.payloads.append(payload)
        if self.timeout:
            yield {"author": "store_manager_agent", "actions": {"state_delta": {"ui:trace:root": {"spans": [
                {"id": "pending", "kind": "model", "agent": "root", "name": "model", "status": "running",
                 "start_ms": 1000, "duration_ms": None}]}}}}
            await asyncio.sleep(30)
        elif self.confirmation and isinstance(payload, str):
            yield {"author": "store_manager_agent", "invocation_id": "turn", "long_running_tool_ids": ["confirmation"],
                   "content": {"parts": [{"function_call": {"id": "confirmation", "name": "adk_request_confirmation",
                       "args": {"originalFunctionCall": {"name": "create_store_task", "args": {}},
                                "toolConfirmation": {"hint": "Create a task"}}}}]}}
        else:
            yield {"author": "store_manager_agent", "content": {"parts": [{"text": "Seven units are recorded."}]}}


def case():
    return {"id": "broad-test", "domain": "inventory", "persona": "manager", "turns": [
        {"question": "How much stock is recorded?", "oracle": [{"id": "units", "value": 7}],
         "criteria": ["Report seven recorded units."]}]}


@pytest.mark.asyncio
async def test_no_judge_is_needs_review_and_never_false_quality_pass(tmp_path):
    result = await run_case(Target(), case(), tmp_path, 1, None)
    assert result["status"] == "needs_review"
    assert not result["turns"][0]["execution_errors"]
    assert (tmp_path / "broad-test/turn-1-events.jsonl").exists()
    assert result["turns"][0]["final_text"] == "Seven units are recorded."


@pytest.mark.asyncio
async def test_write_confirmation_is_declined_and_reported_as_unexpected(tmp_path):
    target = Target(confirmation=True)
    result = await run_case(target, case(), tmp_path, 1, None)
    assert target.payloads[1]["confirmed"] is False
    assert result["status"] == "fail"
    assert any("Read-only question" in error for error in result["turns"][0]["execution_errors"])


@pytest.mark.asyncio
async def test_timeout_preserves_partial_trace_and_never_retries(tmp_path):
    target = Target(timeout=True)
    result = await run_case(target, case(), tmp_path, 0.02, None)
    assert len(target.payloads) == 1
    assert result["status"] == "fail" and result["turns"][0]["timed_out"]
    assert result["turns"][0]["metrics"]["span_count"] == 1
    assert "pending" in (tmp_path / "broad-test/turn-1-events.jsonl").read_text()


def test_percentiles_and_summary_keep_failures_visible():
    assert percentile(range(1, 101), 50) == 50
    assert percentile(range(1, 101), 95) == 95
    summary = summarize([{"status": "fail", "turns": [{"latency_s": 180, "timed_out": True,
                         "execution_errors": ["timeout"], "metrics": {"model_calls": 1, "tool_calls": 0}}]}])
    assert summary["timeouts"] == 1
    assert summary["latency_all_turns_seconds"]["p95"] == 180
    assert summary["latency_successful_turns_seconds"]["p95"] is None


def test_full_report_is_sampled_for_judge_with_real_count_and_metadata():
    from eval.run_broad import product_ids, report_for_judge
    report = {"ui:report": {"id": "inventory-report", "resource": "inventory", "complete": True,
              "total_matching": 600, "columns": ["product_id", "on_hand"],
              "rows": [{"product_id": f"P-{index:04d}", "on_hand": index} for index in range(600)]}}
    bounded = report_for_judge(report)
    assert bounded["ui:report"]["complete"] is True
    assert bounded["ui:report"]["total_matching"] == 600
    assert bounded["ui:report"]["rows"]["observed_row_count"] == 600
    assert len(bounded["ui:report"]["rows"]["sample_rows"]) == 9
    assert {"P-0000", "P-0599"} <= product_ids(bounded)
    assert len(report["ui:report"]["rows"]) == 600


@pytest.mark.asyncio
async def test_quality_pass_does_not_hide_missed_latency_target(tmp_path):
    class Judge:
        async def grade(self, *args):
            return {"decision": "pass"}
    scenario = case()
    scenario["latency_target_seconds"] = 0
    result = await run_case(Target(), scenario, tmp_path, 1, Judge())
    assert result["quality_status"] == "pass"
    assert result["latency_status"] == "fail"
    assert result["status"] == "latency_fail"


def test_guest_supplement_uses_independent_dated_review_evidence(source_snapshot):
    from eval.broad_scenarios import build_guest_dataset
    dataset = build_guest_dataset(source_snapshot)
    assert len(dataset["cases"]) == 6
    assert len({c["turns"][0]["question"] for c in dataset["cases"]}) == 6
    assert all(c["id"].startswith("guest-") and c["latency_target_seconds"] == 35 for c in dataset["cases"])
    product = dataset["cases"][0]["turns"][0]["oracle"][0]["value"]
    assert len(product["latest_dated_reviews"]) == 3
    assert product["stored_review_count"] >= 3
    assert all(row["review_id"] and row["created_at"] and row["body"] for row in product["latest_dated_reviews"])
    assert "reviews" in dataset["source_sha256"]
    alternatives = dataset["cases"][2]["turns"][0]["oracle"][1]["value"]
    assert alternatives and all(row["catalog"]["price_usd"] < product["catalog"]["price_usd"] for row in alternatives)
