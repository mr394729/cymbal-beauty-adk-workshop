---
name: google-adk
description: Google Agent Development Kit (ADK) 2.x for Python, verified against the pinned google-adk 2.9.0. Use when creating or changing agents (LlmAgent, sub-agent modes chat/task/single_turn, Sequential/Parallel/Loop agents, Workflow graphs), tools (FunctionTool, BigQueryToolset, McpToolset, AgentTool), session state and {key?} templating, callbacks and plugins, App and human-in-the-loop confirmation, the adk CLI (web, run, eval, deploy), or evalsets, criteria and the pytest eval gate. Not for deploying or operating agents on Agent Runtime (see agent-platform-runtime), raw Gemini SDK calls (see gemini-genai) or the workshop's data model (see cymbal-beauty-domain).
metadata:
  workshop: cymbal-beauty-adk-workshop
  version: "1.0"
  verified: "2026-09-12"
---

# Google ADK 2.x

ADK is the code-first agent framework this workshop builds on. The running example is
`agents/cymbal_store_ops` (root coordinator, a chat sub-agent, a `single_turn` agent-as-tool and a
`task` agent with a confirmation step). Everything below was checked with `uv run python` against
the installed `google-adk==2.9.0`; when a blog post or an older skill disagrees, this file wins.

## When to use

- Writing or refactoring any code under `agents/`, `notebooks/`, `quickstarts/`.
- Choosing between a sub-agent transfer, an agent-as-tool (`single_turn`), a `task` agent or a plain tool.
- Adding state keys, instruction templates, callbacks, plugins or a confirmation (HITL) step.
- Authoring or debugging evalsets, `test_config.json`, the pytest gate, user or environment simulation.
- Running the agent locally (`uv run adk web agents --port 8000`, `uv run adk run agents/cymbal_store_ops`, `InMemoryRunner`) or reading `adk` CLI flags.

## Facts that override older docs

- Docs live at https://adk.dev/ (the old `google.github.io/adk-docs` host is retired). `adk.dev/llms.txt` exists.
- `LlmAgent` (alias `Agent`) has `mode: Literal['chat','task','single_turn'] | None`. At construction the
  parent removes `task`/`single_turn` children from `transfer_to_agent` targets and appends them to its own
  `tools` as `_TaskAgentTool` / `_SingleTurnAgentTool`, with the tool signature taken from the child's
  `input_schema`. `task` agents must be leaf agents. Build agents with factory functions; never share instances.
- `App(name=, root_agent=, plugins=[...], resumability_config=ResumabilityConfig(is_resumable=True),
  events_compaction_config=, context_cache_config=)` from `google.adk.apps`. `agent.py` must export
  `root_agent` **and** `app`; `adk web`/`adk run` and `AdkApp(app=app)` both discover them.
- Instruction templates: `{key}` raises `KeyError` when the state key is absent, `{key?}` is optional,
  `{user:key}` and `{app:key}` work. Only inject keys you own (`{user:first_name?}`, `{user:store_id?}`).
- State prefixes: none = session, `user:` = per user across sessions, `app:` = global, `temp:` = this
  invocation only. `output_key="last_osa"` writes the agent's final text into state.
- BigQuery tools: `from google.adk.integrations.bigquery import BigQueryToolset, BigQueryCredentialsConfig`
  and `from google.adk.integrations.bigquery.config import BigQueryToolConfig, WriteMode`
  (`google.adk.tools.bigquery` is a shim). `tool_filter` takes strings:
  `["list_table_ids", "get_table_info", "execute_sql"]`. Full tool list: `list_dataset_ids`,
  `get_dataset_info`, `list_table_ids`, `get_table_info`, `get_job_info`, `execute_sql`, `forecast`,
  `analyze_contribution`, `detect_anomalies`, `ask_data_insights`, `search_catalog`.
  `BigQueryToolConfig(write_mode=WriteMode.BLOCKED, max_query_result_rows=50, maximum_bytes_billed=...,
  job_labels={...}, compute_project_id=, location=, application_name=)`. `BigQueryCredentialsConfig`
  needs `credentials=google.auth.default(scopes=[...])[0]`; it fails loudly without ADC.
- MCP: `McpToolset(connection_params=StreamableHTTPConnectionParams(url=..., timeout=30,
  sse_read_timeout=300), tool_filter=[...], header_provider=lambda ctx: {...})`; all keyword-only,
  `header_provider` is evaluated per session so rotating tokens work. `StdioConnectionParams(server_params=
  StdioServerParameters(command=, args=))` for local servers.
- HITL: `FunctionTool(fn, require_confirmation=True)` for yes/no, or inside a tool
  `tool_context.request_confirmation(hint=, payload=)` then read `tool_context.tool_confirmation`
  (`hint`, `confirmed`, `payload`) on the resumed call. Requires the `App` to be resumable. Make the
  write idempotent: the tool may run more than once.
- Callbacks on `LlmAgent`: `before/after_agent_callback`, `before/after_model_callback`,
  `before/after_tool_callback`, `on_model_error_callback`, `on_tool_error_callback`. Plugins add
  `on_user_message_callback`, `before/after_run_callback`, `on_event_callback`, `on_agent_error_callback`.
  Model callbacks receive `(callback_context, llm_request)`; tool callbacks `(tool, tool_args, tool_context)`.
- Workflow graphs: `from google.adk.workflow import Workflow, node, START, DEFAULT_ROUTE, JoinNode, RetryConfig`;
  `@node(retry_config=RetryConfig(...), timeout=...)`.
- `adk eval` prints a summary and **never exits non-zero** on failed cases. The CI gate is
  `AgentEvaluator.evaluate(agent_module=, eval_dataset_file_path_or_dir=, num_runs=2)` which raises
  `AssertionError` on a threshold breach. It has no `config_file_path` argument: it reads
  `test_config.json` **next to the evalset**; a directory argument only picks up `*.test.json` files.
  Custom metrics need `register_custom_metrics_from_config(eval_config)` first (see references/evals.md).
- `adk deploy agent_engine` current flags: `--project --region --display_name --description
  --agent_engine_id --otel_to_cloud --session_service_uri --memory_service_uri --artifact_service_uri
  --adk_version --extra_packages --agent_engine_config_file --trigger_sources`. Deprecated and ignored:
  `--staging_bucket --env_file --requirements_file --adk_app --trace_to_cloud`.
- Model: `gemini-3.8-flash` with `GOOGLE_GENAI_USE_VERTEXAI=TRUE` and `GOOGLE_CLOUD_LOCATION=global`
  (regional locations return 404 for Gemini 3.x). Do not write `gemini-3-flash-preview` or `gemini-2.x`.
- Do not wrap agent code in broad `try/except`: the framework drives retries, errors and resumption.

## Repo map

| Path | Purpose |
|---|---|
| `agents/cymbal_store_ops/agent.py` | `root_agent` + `app = App(...)`; factories in `sub_agents/` |
| `agents/cymbal_store_ops/{tools,callbacks.py,prompts/,config/envs/}` | domain tools over `DataBackend`, PII mask, store scope, role and dataset allowlist callbacks, prompt files, per-env YAML |
| `agents/cymbal_store_ops/AGENTS.md` | the agent tree, invariants, what to run after a change |
| `quickstarts/10-multi-agent-router/patterns/0*.py` | small runnable pattern scripts (`uv run python quickstarts/10-multi-agent-router/patterns/01_coordinator_vs_single_turn.py`) |
| `eval/`, `tests/eval/test_golden.py` | evalsets, `test_config.json`, user/env-sim, the pytest gate |
| `quickstarts/` | one folder per pattern (`uv run python scripts/quickstart_apps.py && uv run adk web build/quickstart_apps --port 8001` opens them in `adk web`) |
| `docs/COMMANDS.md` | the common commands: dev UI, terminal chat, tests, smoke, the evaluation gate |

## Recipes

### Inspect the current coordinator

The running application is maintained in `agents/cymbal_store_ops/agent.py`. Use its
`make_root_agent()` factory rather than copying a simplified second implementation from a guide.
It registers direct evidence tools, three single-turn specialists, the development chat agent,
the task agent and `make_daily_briefing_tool()`.

The briefing is a `SequentialAgent` wrapping three parallel code readers and one writer. Its AgentTool
wrapper can deliver a sole successful result directly; this differs from a generic consultant round trip.
See `agents/cymbal_store_ops/sub_agents/daily_briefing.py` and the nested AGENTS.md for current contracts.

### Read-only BigQuery toolset with labels

```python
import google.auth
from google.adk.integrations.bigquery import BigQueryToolset, BigQueryCredentialsConfig
from google.adk.integrations.bigquery.config import BigQueryToolConfig, WriteMode

creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
toolset = BigQueryToolset(
    tool_filter=["list_table_ids", "get_table_info", "execute_sql"],
    credentials_config=BigQueryCredentialsConfig(credentials=creds),
    bigquery_tool_config=BigQueryToolConfig(write_mode=WriteMode.BLOCKED, max_query_result_rows=50,
        maximum_bytes_billed=100 * 1024 * 1024, job_labels={"adk_agent": "cymbal_store_ops", "env": env}),
)
```

### Guardrail callbacks

```python
from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse

def mask_pii_before_model(callback_context: CallbackContext, llm_request: LlmRequest) -> LlmResponse | None:
    for content in llm_request.contents:
        for part in content.parts or []:
            if part.text:
                part.text = EMAIL_RE.sub("[email]", PHONE_RE.sub("[phone]", part.text))
    return None  # None = continue; returning an LlmResponse short-circuits the model call

def enforce_dataset_allowlist_before_tool(tool, tool_args, tool_context) -> dict | None:
    if tool.name == "execute_sql":
        assert_select_only(tool_args["query"], table_prefix=f"{project}.cymbal_beauty_{namespace}_{env}.")
    return None  # a dict here replaces the tool result without calling the tool
```

### Confirmation inside a tool (HITL)

```python
def create_store_task(task_type: str, product_id: str | None, assignee_id: str | None, note: str,
                      tool_context: ToolContext) -> dict:
    if not tool_context.tool_confirmation:
        tool_context.request_confirmation(hint=f"Create a {task_type} task?", payload={"task_type": task_type})
        return {"status": "PENDING_CONFIRMATION"}
    if not tool_context.tool_confirmation.confirmed:
        return {"status": "CANCELLED"}
    store_id = tool_context.state["user:store_id"]              # scope from state, never from arguments
    key = task_key(store_id, task_type, product_id, assignee_id, note)   # idempotency: a retry returns the original
    return backend.create_store_task(store_id, task_type, product_id, assignee_id, note, task_key=key)
```

### Run locally without the web UI

```python
from google.adk.runners import InMemoryRunner
from google.genai import types
runner = InMemoryRunner(app=app)
session = await runner.session_service.create_session(app_name=app.name, user_id="u1",
        state={"user:user_id": "U-M014", "user:store_id": "S-014", "user:role": "store_manager"})
async for event in runner.run_async(user_id="u1", session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text="Give me my start-of-day plan.")])):
    print(event.author, [p.function_call.name for p in event.content.parts if p.function_call] if event.content else "")
```

### Eval gate in pytest

```python
import pytest
from google.adk.evaluation.agent_evaluator import AgentEvaluator

@pytest.mark.asyncio
async def test_golden():
    await AgentEvaluator.evaluate(agent_module="agents.cymbal_store_ops",
                                  eval_dataset_file_path_or_dir="eval/evalsets/golden.evalset.json",
                                  num_runs=2)   # raises AssertionError on any threshold breach
```

Everything about criteria, evalset JSON, user-sim and env-sim is in [references/evals.md](references/evals.md).

## Gotchas

- Mode wiring mutates the parent's `tools` at construction: build fresh instances per parent.
- `single_turn` agents see no history (`include_contents="none"` is the point); pass what they need via `input_schema`.
- Plugins registered on `App` also apply inside wrapped agents and `AgentTool(include_plugins=True)`.
- A `BLOCKED` `execute_sql` error is a tool result the model can retry; forbid retries in the prompt and assert it in evals.
- `tool_trajectory_avg_score` compares names **and args**; exact args on `execute_sql` are infeasible, use the
  custom `data_tool_trajectory` metric for the SQL tools.
- `IN_ORDER` with an empty expected list always passes; use `EXACT` for "no tool call" cases.
- `adk web agents` serves every folder under `agents/` that has `__init__.py` importing `agent`.
- Filter `UserWarning` only for `google.adk` experimental features; never silence everything.
- Session services: `sqlite://` needs `google-adk[db]` (not installed here); use `memory://` or `agentengine://<id>`.

## References

- [references/adk-2x-api.md](references/adk-2x-api.md), verified signatures and CLI flags
- [references/evals.md](references/evals.md), evalset schema, criteria, gate, simulators, custom metrics
- Agents and routing: https://adk.dev/agents/llm-agents/ , https://adk.dev/agents/routing/
- Collaboration modes and patterns: https://adk.dev/workflows/collaboration/ , https://adk.dev/workflows/patterns/
- Workflow agents and graphs: https://adk.dev/agents/workflow-agents/ , https://adk.dev/graphs/
- State, sessions, memory: https://adk.dev/sessions/state/ , https://adk.dev/sessions/session/ , https://adk.dev/sessions/memory/
- Callbacks and plugins: https://adk.dev/callbacks/types-of-callbacks/ , https://adk.dev/plugins/
- Tools: https://adk.dev/tools-custom/function-tools/ , https://adk.dev/tools-custom/confirmation/ , https://adk.dev/tools-custom/mcp-tools/ , https://adk.dev/integrations/bigquery/
- Runtime and resume: https://adk.dev/runtime/ , https://adk.dev/runtime/resume/
- Evaluate: https://adk.dev/evaluate/ , https://adk.dev/evaluate/criteria/ , https://adk.dev/evaluate/custom_metrics/ , https://adk.dev/evaluate/user-sim/ , https://adk.dev/evaluate/environment_simulation/
- Deploy: https://adk.dev/deploy/agent-runtime/ , https://adk.dev/deploy/agent-runtime/deploy/
- Safety: https://adk.dev/safety/ ; samples: https://github.com/google/adk-samples ; source: https://github.com/google/adk-python
