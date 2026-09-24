# Evaluating ADK agents (verified against google-adk 2.9.0, 2026-09-12)

## Where things live in this repo

| Path | Purpose |
|---|---|
| `eval/build_eval_set.py` | builds `golden.evalset.json` from `EvalCase`/`Invocation` objects (no hand-written JSON) |
| `eval/evalsets/golden.evalset.json` + `test_config.json` | the seven golden cases and their criteria |
| `eval/scenarios/` | user-simulation scenarios, session input, eval config |
| `eval/envsim/` | an eval-only `App` with the environment-simulation plugin |
| `eval/metrics.py` | custom metric `data_tool_trajectory` |
| `eval/vertex_eval.py`, `eval/remote_eval.py` | Agent Platform evaluation of a deployed engine / revision |
| `tests/eval/test_golden.py` | **the CI gate** (`uv run pytest tests/eval -q -k test_golden_gate_passes`), exit code = result |

## Evalset JSON shape

```json
{
  "eval_set_id": "golden",
  "eval_cases": [
    {
      "eval_id": "osa_explanation",
      "conversation": [
        {
          "invocation_id": "inv-1",
          "user_content": {"role": "user", "parts": [{"text": "Why is Lumière Hydra Cream flagged?"}]},
          "final_response": {"role": "model", "parts": [{"text": "P-0101: 0 on shelf, 7 in the backroom, 7 on hand; backroom check."}]},
          "intermediate_data": {
            "tool_uses": [{"name": "inventory_excellence", "args": {"product_name": "Lumière Hydra Cream"}}],
            "tool_responses": [],
            "intermediate_responses": []
          }
        }
      ],
      "session_input": {"app_name": "cymbal_store_ops", "user_id": "eval", "state": {"user:user_id": "U-M014", "user:store_id": "S-014", "user:role": "store_manager"}}
    }
  ]
}
```

A transfer shows up as a tool use named `transfer_to_agent` with `{"agent_name": "associate_development"}`; a
workflow behind `AgentTool` shows up as one tool use named after the agent (`daily_briefing`).
Each golden case runs in a fresh session (`session_input` seeds the state the app would seed).

## test_config.json (criteria)

```json
{
  "criteria": {
    "tool_trajectory_avg_score": {"threshold": 1.0, "match_type": "IN_ORDER"},
    "response_match_score": 0.6,
    "final_response_match_v2": {"threshold": 0.7,
      "judge_model_options": {"judge_model": "gemini-3.8-flash", "num_samples": 3}},
    "safety_v1": 0.9
  }
}
```

- `match_type`: `EXACT` (whole sequence), `IN_ORDER` (expected calls in sequence, extras allowed),
  `ANY_ORDER`. `IN_ORDER` with no expected calls always passes; use `EXACT` for no-tool cases.
- Trajectory matching compares tool **names and args**. Exact SQL text is unstable, so the repo scores the
  three SQL tools by name only through a custom metric (below).
- `safety_v1`, `multi_turn_*` and `hallucinations_v1` are judged through the Agent Platform evaluation
  service: they need `GOOGLE_CLOUD_PROJECT`, ADC and `aiplatform.googleapis.com`.
- Judge model: pin `gemini-3.8-flash` with `num_samples: 3`; the docs' `gemini-flash-latest` alias is not
  the workshop choice.

## The pytest gate

```python
# tests/eval/test_golden.py
import pytest
from google.adk.evaluation.agent_evaluator import AgentEvaluator
from google.adk.evaluation.metric_evaluator_registry import register_custom_metrics_from_config

EVALSET = "eval/evalsets/golden.evalset.json"

@pytest.mark.asyncio
async def test_golden_gate():
    register_custom_metrics_from_config(AgentEvaluator.find_config_for_test_file(EVALSET))
    await AgentEvaluator.evaluate(agent_module="agents.cymbal_store_ops",
                                  eval_dataset_file_path_or_dir=EVALSET, num_runs=2)
```

`AgentEvaluator.evaluate` asserts `not failures` and raises `AssertionError` listing every failed
(case, metric); pytest turns that into a non-zero exit. `adk eval` (`uv run adk eval agents/cymbal_store_ops eval/evalsets/golden.evalset.json --config_file_path eval/evalsets/test_config.json --print_detailed_results`) is for reading
per-case detail, never for gating. `adk eval` registers custom metrics from the config file by itself;
`AgentEvaluator` does not, hence the explicit call above.

## Custom metrics

```json
{
  "criteria": {"data_tool_trajectory": 1.0},
  "custom_metrics": {
    "data_tool_trajectory": {
      "code_config": {"name": "eval.metrics.data_tool_trajectory"},
      "metric_info": {"metric_name": "data_tool_trajectory", "description": "IN_ORDER on names; args ignored for SQL tools",
                      "metric_value_info": {"interval": {"min_value": 0.0, "max_value": 1.0}}}
    }
  }
}
```

```python
# eval/metrics.py
def data_tool_trajectory(eval_metric: EvalMetric, actual_invocations: list[Invocation],
                         expected_invocations: list[Invocation] | None,
                         conversation_scenario: ConversationScenario | None) -> EvaluationResult:
    ...  # compare tool names in order; for execute_sql also assert_select_only(args["query"])
```

## Deterministic "break it" (notebook 04)

`STORE_OPS_FAULT=stale_stock uv run pytest tests/eval -q -k test_golden_gate_passes` makes `check_store_stock` return a wrong on-hand quantity; the
`stock_invariant` metric (hero product on-hand = 7) fails and the gate exits 1. `STORE_OPS_FAULT=stale_backlog`
zeroes the pending BOPIS count, so `plan_invariant` and `coverage_invariant` fail. Nothing in the prompts was
deleted; reverting the variable makes it green again. `uv run python eval/compare_models.py --models a,b` runs the same gate per
model and writes `build/model_regression.md`.

## User simulation

`eval/scenarios/user_sim.scenarios.json`:

```json
{"scenarios": [{"starting_prompt": "I have dry skin and a wedding in two weeks.",
                "conversation_plan": "Get a simple regimen, check stock at Naperville, ask about points.",
                "user_persona": "NOVICE"}]}
```

`eval/scenarios/session_input.json`: `{"app_name": "cymbal_store_ops", "user_id": "sim", "state": {"user:user_id": "U-M014", "user:store_id": "S-014", "user:role": "store_manager"}}`.
`eval/scenarios/user_sim.eval_config.json`:

```json
{"criteria": {"hallucinations_v1": {"threshold": 0.5, "evaluate_intermediate_nl_responses": true},
              "multi_turn_task_success_v1": 0.7, "safety_v1": 0.8},
 "user_simulator_config": {"type": "llm_backed", "model": "gemini-3.8-flash", "max_allowed_invocations": 10}}
```

```bash
uv run adk eval_set create agents/cymbal_store_ops user_sim
uv run adk eval_set add_eval_case agents/cymbal_store_ops user_sim \
  --scenarios_file eval/scenarios/user_sim.scenarios.json --session_input_file eval/scenarios/session_input.json
uv run adk eval agents/cymbal_store_ops user_sim --config_file_path eval/scenarios/user_sim.eval_config.json --print_detailed_results
```

Personas: `NOVICE`, `EXPERT`, `EVALUATOR` (pre-built) or a `UserPersona(id, description, behaviors)` object.

## Environment simulation

```python
from google.adk.tools.environment_simulation import EnvironmentSimulationFactory
from google.adk.tools.environment_simulation.environment_simulation_config import (
    EnvironmentSimulationConfig, ToolSimulationConfig, InjectionConfig, InjectedError)

cfg = EnvironmentSimulationConfig(tool_simulation_configs=[ToolSimulationConfig(
    tool_name="check_store_stock",
    injection_configs=[InjectionConfig(match_args={"product_name": "Lumière Hydra Cream"}, injection_probability=1.0,
                                       injected_error=InjectedError(injected_http_error_code=503,
                                                                    error_message="inventory service unavailable"))])])
app = App(name="cymbal_store_ops_envsim", root_agent=make_root(),
          plugins=[EnvironmentSimulationFactory.create_plugin(cfg)])
```

`InjectionConfig` also supports `injected_latency_seconds` (up to 120) and `injected_response`.
Run it as its own agent folder (`eval/envsim/`) with a criteria file that expects a graceful answer
(`hallucinations_v1` 0.5) rather than the fixture quantity.

## Agent Platform evaluation of a deployed engine

`eval/vertex_eval.py`: `client.evals.run_inference(agent=<engine resource name>, ...)` then
`client.evals.evaluate(...)` with prebuilt metrics (final response quality, tool use quality, multi-turn task
success, safety); results appear in the Console. `eval/remote_eval.py` does the same against one **revision**
(`client.agent_engines.runtimes.revisions.get(name=...).query(...)`) and records engine, revision and release
manifest. Docs: https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/agent-evaluation
