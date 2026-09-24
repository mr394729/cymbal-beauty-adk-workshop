# Saved golden evaluations in Vertex

`publish_vertex.py` publishes saved ADK responses, references and matched tool evidence to a native Evaluation Service experiment and run. It does not rerun the store agent or execute store tools. This makes a historical golden run inspectable in the service without treating the original custom operational invariants as service-computed scores.

Prepare first; add `--apply` to create resources and run the managed response-match metric:

```bash
uv run python eval/publish_vertex.py \
  --source build/eval_runs/RUN/cymbal_store_ops/.adk/eval_history/RESULT.evalset_result.json \
  --rescore build/eval_runs/RUN/terminal-response-rescore.json \
  --out build/vertex-evaluation/golden-DATE \
  --namespace demo \
  --dest gs://YOUR-STAGING-BUCKET/evaluations/demo/golden-DATE
```

Omit `--rescore` when the source has none. The destination must end in the publication namespace and output-directory name. The output directory records the resource names and resumes the same run on subsequent `--apply` calls. Use a new output directory for a new source run. Existing cloud IAM governs access; the publisher does not add public access or change IAM.

The manifest records the exact source hash, case/session/invocation mapping, original ADK metric status counts and optional rescore hash. Sanitized source evidence and the rescore are uploaded alongside the service requests. Thought parts, signatures and credential fields are removed; tool results and terminal tool-response evidence are retained. Original timestamps, references and thresholds are not rewritten. A `demo` publication label does not rename the namespace of the original evaluation sessions.

The native metric is the Evaluation Service's managed `FINAL_RESPONSE_MATCH` rubric (currently `final_response_match_v2`). Its result is separate from the original ADK reference-match judge and deterministic business invariants. The run is a historical replay, not evidence that a later deployment has passed, and rubric scores alone do not establish factual correctness. The service manages its evaluator; no agent model, thinking setting or deployment is changed.

API limitation observed on 21 September 2026: `EvaluationRunMetric` exposed ROUGE in the installed SDK but the service rejected that computation metric. The publisher therefore uses only the managed reference-match metric. The initial rejected request/experiment is retained in the local verification record rather than presented as a completed run.

The implementation uses the installed SDK's public `create_evaluation_item`, `create_evaluation_set`, `create_evaluation_experiment`, `create_evaluation_run`, and `get_evaluation_run` methods. No `agent`, `agent_info` or `inference_configs` argument is supplied: those would request fresh inference. See the official [agent evaluation guide](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/evaluation-agents-client) and [evaluation overview](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/evaluation-overview).

Native agent evaluation uses `CandidateResponse.agent_data`: the saved agents map contains the actual recorded instructions and tool declarations, and each saved turn contains user, tool, intermediate and final events. Flat response text plus `events` is insufficient for this service's agent metrics: a diagnostic run ignored evidence and treated an appropriate scope refusal as failure. That diagnostic is retained separately. The corrected publisher uses the native trace contract; it does not change the answer or reference to improve a score.

`service-results.json` and `result-items/` retain actual per-item verdicts and service errors. A service run state of `SUCCEEDED` means processing ended; inspect failed-item counts and scores before describing its quality. No new pass threshold is imposed by this publisher.

For an explicitly selected follow-up run, `--case CASE_ID` includes its saved replicates and `--experiment RESOURCE_NAME` attaches that run to an existing experiment. Use a new output directory. The publisher refuses to reuse existing cloud resources with changed normalized answers or evidence. Native extraction also requires terminal tool responses and final text in consecutive events; their original content and ordering are preserved. The final assistant text receives `role="model"` because ADK places it inside a protocol-level `role="user"` function-response envelope. This normalization is recorded in the manifest and covered by a regression test.
