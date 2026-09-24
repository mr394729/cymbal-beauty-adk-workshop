"""Publish saved ADK golden turns to a native Vertex Evaluation experiment/run.

No agent inference or store calls. Dry preparation is the default; --apply uploads
sanitized source evidence and asks the Evaluation Service to score saved replies.
Original ADK metrics remain provenance, separate from new service metrics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from collections import Counter
from pathlib import Path

REDACT_KEYS = {
    "thought_signature",
    "authorization",
    "access_token",
    "id_token",
    "x-cymbal-session",
    "x-cymbal-caller-token",
}


def clean(value):
    """Keep actual evidence; remove private thinking/signatures and credentials."""
    if isinstance(value, dict):
        if value.get("thought") is True:
            return None
        return {
            k: clean(v) for k, v in value.items() if k.lower() not in REDACT_KEYS and k != "thought"
        }
    if isinstance(value, list):
        return [
            clean(item)
            for item in value
            if not (isinstance(item, dict) and item.get("thought") is True)
        ]
    return value


def content_text(content):
    return "\n".join(
        p["text"]
        for p in (content or {}).get("parts", [])
        if p.get("text") and p.get("thought") is not True
    )


def agent_data(actual, session):
    """Map saved ADK configuration and events to the service's agent trace contract."""
    details = (actual.get("app_details") or {}).get("agent_details") or {}
    agents = {
        name: {
            "agent_id": name,
            "instruction": detail.get("instructions", ""),
            "tools": clean(detail.get("tool_declarations") or []),
        }
        for name, detail in details.items()
    }
    if not agents:
        raise ValueError(
            "Saved agent instructions/tool declarations are required for native agent evaluation"
        )
    final = actual["final_response"]
    matches = [
        e
        for e in session.get("events", [])
        if content_text(e.get("content")) == content_text(final) and e.get("author") in agents
    ]
    author = matches[-1]["author"] if matches else next(iter(agents))
    events = [{"author": "user", "content": clean(actual["user_content"])}]
    events.extend(
        {"author": e["author"], "content": clean(e["content"])}
        for e in (actual.get("intermediate_data") or {}).get("invocation_events", [])
        if e.get("content")
    )
    final = clean(final)
    # Native final-answer extraction ignores text when a function response is
    # present in the same event. Preserve order and values in separate events.
    tool_parts = [
        p for p in final.get("parts", []) if p.get("function_call") or p.get("function_response")
    ]
    answer_parts = [
        p
        for p in final.get("parts", [])
        if not (p.get("function_call") or p.get("function_response"))
    ]
    for parts in (tool_parts, answer_parts):
        if parts:
            events.append(
                {
                    "author": author,
                    "content": {
                        "role": final.get("role", "user") if parts is tool_parts else "model",
                        "parts": parts,
                    },
                }
            )
    return {
        "agents": agents,
        "turns": [{"turn_index": 0, "turn_id": actual["invocation_id"], "events": events}],
    }


def prepare(
    source: Path,
    out: Path,
    namespace: str,
    rescore: Path | None = None,
    cases: set[str] | None = None,
):
    if not re.fullmatch(r"[a-z][a-z0-9]{2,11}", namespace):
        raise ValueError("Invalid workshop namespace")
    raw = json.loads(source.read_text())
    rows, identities, statuses = [], [], Counter()
    for case in raw["eval_case_results"]:
        if cases and case["eval_id"] not in cases:
            continue
        for index, turn in enumerate(case["eval_metric_result_per_invocation"]):
            actual, expected = turn["actual_invocation"], turn["expected_invocation"]
            prompt, response, reference = [
                content_text(x)
                for x in (
                    actual["user_content"],
                    actual["final_response"],
                    expected["final_response"],
                )
            ]
            if not all((prompt, response, reference)):
                raise ValueError(f"Missing saved prompt/response/reference: {case['eval_id']}")
            events = clean((actual.get("intermediate_data") or {}).get("invocation_events", []))
            # ADK terminal tools can be retained only in final_response. Their
            # matched call IDs and evidence must reach the evaluator as well.
            final_tools = [
                p
                for p in clean(actual["final_response"]).get("parts", [])
                if p.get("function_response") or p.get("function_call")
            ]
            if final_tools:
                events.append(
                    {
                        "author": "store_manager_agent",
                        "content": {"role": "model", "parts": final_tools},
                    }
                )
            row_id = f"{case['eval_id']}:{case['session_id']}:{index}"
            rows.append(
                {
                    "prompt": prompt,
                    "response": response,
                    "reference": reference,
                    "intermediate_events": events,
                    "agent_data": agent_data(actual, case.get("session_details") or {}),
                }
            )
            identities.append(
                {
                    "row": len(rows) - 1,
                    "source_id": row_id,
                    "invocation_id": actual["invocation_id"],
                    "creation_timestamp": actual.get("creation_timestamp"),
                }
            )
            statuses.update(str(m["eval_status"]) for m in turn.get("eval_metric_results", []))
    if not rows:
        raise ValueError("No saved turns in source")
    manifest = {
        "namespace": namespace,
        "namespace_purpose": "Evaluation resource label; source dataset/session scope is unchanged.",
        "source_path": str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "saved_turns": len(rows),
        "selected_cases": sorted(cases or []),
        "fresh_agent_calls": 0,
        "terminal_event_normalization": "Separate existing tool and text parts into consecutive events; assistant answer uses model role because ADK terminal function-response envelope has user role. Content unchanged.",
        "source_metric_status_counts": dict(statuses),
        "source_metric_status_enum": {"1": "PASSED", "2": "FAILED", "0": "NOT_EVALUATED"},
        "source_metric_semantics": "Historical ADK metrics; never imported as Vertex-computed metrics.",
        "vertex_metric_semantics": {
            "final_response_match_v2": "Managed Evaluation Service reference-match rubric over saved agent configuration and execution trace; distinct from historical ADK metrics."
        },
        "rows": identities,
        "sanitization": "Removed thought parts, signatures and credential fields. Kept tool results and terminal tool evidence.",
    }
    if rescore:
        result = json.loads(rescore.read_text())
        if Path(result["source"]).resolve() != source.resolve():
            raise ValueError("Rescore provenance does not match source")
        manifest["rescore"] = {
            "path": str(rescore),
            "sha256": hashlib.sha256(rescore.read_bytes()).hexdigest(),
            "status": result["status"],
            "reason": result["reason"],
        }
    previous_dataset = out / "dataset.json"
    if (
        (out / "resources.json").exists()
        and previous_dataset.exists()
        and json.loads(previous_dataset.read_text()) != rows
    ):
        raise ValueError(
            "Existing resources use a different prepared dataset; choose a new output directory"
        )
    manifest["dataset_sha256"] = hashlib.sha256(
        json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    out.mkdir(parents=True, exist_ok=True)
    (out / "dataset.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    (out / "source-evidence.json").write_text(json.dumps(clean(raw), ensure_ascii=False) + "\n")
    if rescore:
        (out / "adk-rescore.json").write_text(
            json.dumps(clean(json.loads(rescore.read_text())), indent=2) + "\n"
        )
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return rows, manifest


def collect_results(client, storage_client, run, out, checkpoint, manifest):
    """Retain raw service verdicts, including errors hidden by SDK parsing."""
    results = run.evaluation_run_results
    if not results or not results.evaluation_set:
        return
    result_set = client.evals.get_evaluation_set(name=results.evaluation_set)
    folder = out / "result-items"
    folder.mkdir(exist_ok=True)
    request_map = {
        name: manifest["rows"][i] for i, name in enumerate(checkpoint.get("evaluation_items", []))
    }
    items = []
    for index, name in enumerate(result_set.evaluation_items or []):
        item = client.evals.get_evaluation_item(name=name)
        if not item.gcs_uri:
            items.append({"name": name, "error": "No result GCS URI"})
            continue
        bucket_name, blob_name = item.gcs_uri[5:].split("/", 1)
        raw = json.loads(storage_client.bucket(bucket_name).blob(blob_name).download_as_text())
        (folder / f"{index:02d}.json").write_text(json.dumps(raw, indent=2) + "\n")
        request = raw.get("evaluationRequest", raw.get("evaluation_request"))
        items.append(
            {
                "name": name,
                "source": request_map.get(request),
                "results": raw.get("candidateResults", raw.get("candidate_results", [])),
            }
        )
    summary = {
        "run": run.name,
        "state": getattr(run.state, "value", str(run.state)),
        "service_summary": results.summary_metrics.model_dump(mode="json", exclude_none=True)
        if results.summary_metrics
        else {},
        "interpretation": "Service scores, not a replacement for ADK gate thresholds. SUCCEEDED does not imply every item was scored or passed.",
        "items": items,
    }
    (out / "service-results.json").write_text(json.dumps(summary, indent=2) + "\n")


def apply(args, rows, manifest):
    import vertexai
    from google.cloud import storage
    from vertexai import types

    if not args.dest.startswith("gs://") or not args.dest.rstrip("/").endswith(
        "/" + args.namespace + "/" + args.out.name
    ):
        raise ValueError("Destination must end with /<namespace>/<output-directory-name>")
    client = vertexai.Client(project=args.project, location=args.location)
    checkpoint_path = args.out / "resources.json"
    checkpoint = json.loads(checkpoint_path.read_text()) if checkpoint_path.exists() else {}
    if checkpoint and checkpoint["source_sha256"] != manifest["source_sha256"]:
        raise ValueError("Output directory already refers to a different source")
    bucket_name, prefix = args.dest[5:].split("/", 1)
    storage_client = storage.Client(project=args.project)
    bucket = storage_client.bucket(bucket_name)
    for name in ("manifest.json", "dataset.json", "source-evidence.json", "adk-rescore.json"):
        path = args.out / name
        if path.exists():
            bucket.blob(prefix.rstrip("/") + "/provenance/" + name).upload_from_filename(
                path, content_type="application/json"
            )
    checkpoint.update(
        {
            "source_sha256": manifest["source_sha256"],
            "provenance": args.dest + "/provenance/manifest.json",
        }
    )
    labels = {"namespace": args.namespace, "purpose": "saved-golden-evaluation", "source": "adk"}
    if args.experiment and not checkpoint.get("experiment"):
        checkpoint["experiment"] = args.experiment
        checkpoint_path.write_text(json.dumps(checkpoint, indent=2) + "\n")
    if not checkpoint.get("experiment"):
        experiment = client.evals.create_evaluation_experiment(
            display_name=f"{args.namespace} — store operations golden — saved agent traces",
            labels=labels,
            metadata={
                "source_manifest": checkpoint["provenance"],
                "source_sha256": manifest["source_sha256"],
                "historical_adk_metrics": "Separate provenance; not service-computed scores",
                "fresh_agent_calls": 0,
            },
        )
        checkpoint["experiment"] = experiment.name
        checkpoint_path.write_text(json.dumps(checkpoint, indent=2) + "\n")
    if not checkpoint.get("run"):
        if not checkpoint.get("evaluation_set"):
            items = checkpoint.setdefault("evaluation_items", [])
            for index, row in enumerate(rows):
                if index < len(items):
                    continue
                request = types.EvaluationItemRequest(
                    prompt=types.EvaluationPrompt(text=row["prompt"]),
                    golden_response=types.CandidateResponse(text=row["reference"]),
                    candidate_responses=[
                        types.CandidateResponse(
                            candidate="saved-adk-golden",
                            agent_data=types.evals.AgentData.model_validate(row["agent_data"]),
                        )
                    ],
                )
                item_path = prefix.rstrip("/") + f"/requests/{index:03d}.json"
                bucket.blob(item_path).upload_from_string(
                    request.model_dump_json(exclude_none=True), content_type="application/json"
                )
                item = client.evals.create_evaluation_item(
                    evaluation_item_type=types.EvaluationItemType.REQUEST,
                    gcs_uri=f"gs://{bucket_name}/{item_path}",
                    display_name=f"{args.namespace}-{manifest['rows'][index]['source_id']}",
                )
                items.append(item.name)
                checkpoint_path.write_text(json.dumps(checkpoint, indent=2) + "\n")
            evaluation_set = client.evals.create_evaluation_set(
                evaluation_items=items,
                display_name=f"{args.namespace} saved golden {args.out.name}",
            )
            checkpoint["evaluation_set"] = evaluation_set.name
            checkpoint_path.write_text(json.dumps(checkpoint, indent=2) + "\n")
        dataset = types.EvaluationRunDataSource(evaluation_set=checkpoint["evaluation_set"])
        metrics = [types.RubricMetric.FINAL_RESPONSE_MATCH]
        run = client.evals.create_evaluation_run(
            dataset=dataset,
            dest=args.dest + "/service",
            display_name=f"{args.namespace} — {args.out.name} — saved responses",
            metrics=metrics,
            evaluation_experiment=checkpoint["experiment"],
            labels=labels,
        )
        checkpoint["run"] = run.name
        checkpoint_path.write_text(json.dumps(checkpoint, indent=2) + "\n")
    deadline = time.monotonic() + args.wait_seconds
    while True:
        run = client.evals.get_evaluation_run(name=checkpoint["run"])
        state = getattr(run.state, "value", str(run.state))
        result = run.model_dump(mode="json", exclude_none=True)
        (args.out / "vertex-run.json").write_text(json.dumps(result, indent=2) + "\n")
        print(
            json.dumps({"experiment": checkpoint["experiment"], "run": run.name, "state": state}),
            flush=True,
        )
        if (
            state in {"SUCCEEDED", "FAILED", "CANCELLED", "PARTIALLY_SUCCEEDED"}
            or time.monotonic() >= deadline
        ):
            break
        time.sleep(15)
    if state in {"SUCCEEDED", "FAILED"}:
        collect_results(client, storage_client, run, args.out, checkpoint, manifest)
    if state == "FAILED":
        raise RuntimeError(f"Evaluation Service run failed; see {args.out / 'vertex-run.json'}")
    return checkpoint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--rescore", type=Path)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument(
        "--experiment", help="Existing native experiment resource for an additional run"
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    parser.add_argument("--location", default="us-central1")
    parser.add_argument("--dest", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=300)
    args = parser.parse_args()
    if args.apply and not args.project:
        raise SystemExit("--project (or GOOGLE_CLOUD_PROJECT) is required to publish")
    rows, manifest = prepare(args.source, args.out, args.namespace, args.rescore, set(args.case))
    print(
        json.dumps(
            {
                "prepared_turns": len(rows),
                "source_sha256": manifest["source_sha256"],
                "apply": args.apply,
            }
        ),
        flush=True,
    )
    if args.apply:
        apply(args, rows, manifest)


if __name__ == "__main__":
    main()
