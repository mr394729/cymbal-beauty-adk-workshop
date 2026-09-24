"""Provenance and evidence conversion for publishing saved golden evaluations."""
import hashlib
import json

import pytest

from eval.publish_vertex import clean, prepare


def source_file(tmp_path):
    part = {"function_response": {"id": "call-1", "name": "daily_briefing", "response": {"units": 7}}}
    raw = {"eval_case_results": [{"eval_id": "case", "session_id": "session",
        "eval_metric_result_per_invocation": [{"actual_invocation": {
            "app_details": {"agent_details": {"root": {"instructions": "Store operations only", "tool_declarations": []}}},
            "invocation_id": "inv", "user_content": {"parts": [{"text": "What is due?"}]},
            "final_response": {"role": "user", "parts": [part, {"text": "Seven units."}]},
            "intermediate_data": {"invocation_events": [{"author": "root", "content": {
                "parts": [{"function_call": {"name": "daily_briefing", "id": "call-1", "args": {}},
                           "thought_signature": "private-signature"}, {"text": "private reasoning", "thought": True}]}}]}},
            "expected_invocation": {"final_response": {"parts": [{"text": "Seven."}]}},
            "eval_metric_results": [{"metric_name": "local_only", "eval_status": 2, "score": 0}]}]}]}
    source = tmp_path / "source.json"
    source.write_text(json.dumps(raw))
    return source


def test_preserves_terminal_evidence_and_historical_failure_separately(tmp_path):
    source = source_file(tmp_path)
    rows, manifest = prepare(source, tmp_path / "out", "demo")
    assert rows[0]["response"] == "Seven units."
    assert rows[0]["reference"] == "Seven."
    data = rows[0]["agent_data"]
    assert data["agents"]["root"]["instruction"] == "Store operations only"
    assert data["turns"][0]["events"][-2]["content"]["parts"][0]["function_response"]["id"] == "call-1"
    assert data["turns"][0]["events"][0]["author"] == "user"
    assert data["turns"][0]["events"][-1]["content"]["parts"] == [{"text": "Seven units."}]
    assert data["turns"][0]["events"][-1]["content"]["role"] == "model"
    assert data["turns"][0]["events"][-2]["content"]["role"] == "user"
    events = rows[0]["intermediate_events"]
    assert events[-1]["content"]["parts"][0]["function_response"]["response"]["units"] == 7
    assert events[0]["content"]["parts"][0]["function_call"]["id"] == "call-1"
    assert manifest["source_metric_status_counts"] == {"2": 1}
    assert manifest["fresh_agent_calls"] == 0
    assert manifest["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    evidence = (tmp_path / "out/source-evidence.json").read_text()
    assert "private-signature" not in evidence and "private reasoning" not in evidence
    assert '"score": 0' in evidence


def test_rescore_must_match_original_source(tmp_path):
    source = source_file(tmp_path)
    rescore = tmp_path / "rescore.json"
    rescore.write_text(json.dumps({"source": "some-other-run.json"}))
    with pytest.raises(ValueError, match="does not match"):
        prepare(source, tmp_path / "out", "demo", rescore)


def test_missing_answer_is_not_fabricated(tmp_path):
    source = source_file(tmp_path)
    raw = json.loads(source.read_text())
    raw["eval_case_results"][0]["eval_metric_result_per_invocation"][0]["actual_invocation"]["final_response"]["parts"].pop()
    source.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="Missing saved"):
        prepare(source, tmp_path / "out", "demo")


def test_sanitizer_preserves_null_evidence_values_and_redacts_credentials():
    # Source nulls convey absent recorded facts and must not turn into zero.
    actual = clean({"required_units": None, "Authorization": "Bearer secret", "rows": [{"units": 0}, None, {"units": 7}]})
    assert "Authorization" not in actual
    assert actual["required_units"] is None
    assert actual["rows"] == [{"units": 0}, None, {"units": 7}]


def test_existing_cloud_resources_cannot_be_relabelled_with_changed_answers(tmp_path):
    source = source_file(tmp_path)
    out = tmp_path / "out"
    prepare(source, out, "demo")
    (out / "resources.json").write_text('{"run": "existing-resource"}')
    before = (out / "dataset.json").read_text()
    raw = json.loads(source.read_text())
    raw["eval_case_results"][0]["eval_metric_result_per_invocation"][0]["actual_invocation"]["final_response"]["parts"][-1]["text"] = "Changed answer"
    source.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="different prepared dataset"):
        prepare(source, out, "demo")
    assert (out / "dataset.json").read_text() == before
