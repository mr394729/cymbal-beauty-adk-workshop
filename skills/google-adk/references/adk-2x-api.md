# ADK 2.9.0 API reference (verified by introspection, 2026-09-12)

Every signature below was printed with `uv run python -c "import inspect, ..."` in the repo venv.
Re-verify after bumping `google-adk` in `pyproject.toml`.

## LlmAgent fields that matter here

| Field | Type / values | Notes |
|---|---|---|
| `name`, `description`, `model` | `str`, `str`, `str \| BaseLlm` | `description` drives LLM routing between sub-agents |
| `instruction`, `global_instruction` | `str \| Callable[[ReadonlyContext], str]` | `{key}` templating; `{key?}` optional; `{user:key}` |
| `mode` | `'chat' \| 'task' \| 'single_turn' \| None` | `None` becomes `chat` when attached to a parent |
| `input_schema` | `type[BaseModel] \| None` | required in practice for `single_turn`/`task` (tool signature) |
| `output_schema` | pydantic type, dict or `genai.types.Schema` | structured final answer |
| `output_key` | `str \| None` | final text written to `state[output_key]` |
| `include_contents` | `'default' \| 'none'` | `'none'` = no conversation history in the model request |
| `sub_agents`, `tools` | `list[BaseAgent]`, `list[Callable \| BaseTool \| BaseToolset]` | modes are wired here at construction |
| `disallow_transfer_to_parent`, `disallow_transfer_to_peers` | `bool` | default `False`; root re-entry relies on the parent transfer |
| `generate_content_config` | `genai.types.GenerateContentConfig` | temperature 0 for specialists in this repo |
| `planner` | `BasePlanner \| None` | not used in the workshop |
| callbacks | see below | single callable or list |

Callback signatures (`google.adk.agents.context.Context` is the base; `CallbackContext` subclasses it):

```python
before_agent_callback(callback_context) -> types.Content | None
after_agent_callback(callback_context) -> types.Content | None
before_model_callback(callback_context, llm_request: LlmRequest) -> LlmResponse | None
after_model_callback(callback_context, llm_response: LlmResponse) -> LlmResponse | None
before_tool_callback(tool: BaseTool, tool_args: dict, tool_context: ToolContext) -> dict | None
after_tool_callback(tool, tool_args, tool_context, tool_response: dict) -> dict | None
on_model_error_callback(callback_context, llm_request, error) -> LlmResponse | None
on_tool_error_callback(tool, tool_args, tool_context, error) -> dict | None
```

## App and plugins

```python
from google.adk.apps import App
from google.adk.apps.app import ResumabilityConfig, EventsCompactionConfig, ContextCacheConfig
App(name: str, root_agent: BaseAgent, plugins: list[BasePlugin] = [],
    events_compaction_config=None, context_cache_config=None, resumability_config=None)
ResumabilityConfig(is_resumable: bool)
```

`BasePlugin` hooks (all keyword-only): `on_user_message_callback(*, invocation_context, user_message)`,
`before_run_callback`, `after_run_callback`, `on_event_callback`, `before/after_agent_callback`,
`before/after_model_callback(*, callback_context, llm_request | llm_response)`,
`before/after_tool_callback(*, tool, tool_args, tool_context [, result])`, `on_agent_error_callback`,
`on_model_error_callback`, `on_tool_error_callback`, `on_run_error_callback`.
Shipped plugins (`google.adk.plugins`): `LoggingPlugin(name='logging_plugin')`, `DebugLoggingPlugin`,
`ContextFilterPlugin`, `GlobalInstructionPlugin`, `ReflectAndRetryToolPlugin`, `SaveFilesAsArtifactsPlugin`,
`BigQueryAgentAnalyticsPlugin`, `AutoTracingPlugin`, `MultimodalToolResultsPlugin`.
`on_user_message_callback` is the right place to redact PII before it is appended to the session.

## Tools

```python
FunctionTool(func, *, require_confirmation: bool | Callable[..., bool] = False)
AgentTool(agent, skip_summarization=False, *, include_plugins=True, propagate_grounding_metadata=False)
ToolContext.request_confirmation(*, hint: str | None = None, payload: Any | None = None) -> None
ToolContext.tool_confirmation -> ToolConfirmation(hint, confirmed, payload) | None
ToolContext.state, .actions, .invocation_id, .function_call_id, .agent_name, .session,
            .load_artifact/.save_artifact, .search_memory, .request_credential, .route
```

BigQuery (`google.adk.integrations.bigquery`):

```python
BigQueryToolset(*, tool_filter: list[str] | ToolPredicate | None = None,
                credentials_config: BigQueryCredentialsConfig | None = None,
                bigquery_tool_config: BigQueryToolConfig | None = None)
BigQueryToolConfig(write_mode=WriteMode.BLOCKED | PROTECTED | ALLOWED, maximum_bytes_billed=None,
                   max_query_result_rows=50, application_name=None, compute_project_id=None,
                   location=None, job_labels: dict[str, str] | None = None)
BigQueryCredentialsConfig(credentials=..., external_access_token_key=None, client_id=None,
                          client_secret=None, scopes=None)
```

Tool names: `get_dataset_info, get_table_info, list_dataset_ids, list_table_ids, get_job_info, execute_sql,
forecast, analyze_contribution, detect_anomalies, ask_data_insights, search_catalog`. BLOCKED = a dry run
whose statement type is not SELECT returns an ERROR envelope. ADK labels every job `adk-bigquery-tool=<tool>`;
`job_labels` keys must be lowercase and must not start with `adk-bigquery-`.

MCP (`google.adk.tools.mcp_tool`):

```python
McpToolset(*, connection_params: StdioConnectionParams | SseConnectionParams | StreamableHTTPConnectionParams,
           tool_filter=None, tool_name_prefix=None, tool_list_cache_ttl_seconds=None, auth_scheme=None,
           auth_credential=None, require_confirmation=False,
           header_provider: Callable[[ReadonlyContext], dict[str, str] | Awaitable[dict[str, str]]] | None = None,
           use_mcp_resources=False, ...)
StreamableHTTPConnectionParams(url, headers=None, timeout=..., sse_read_timeout=..., terminate_on_close=...)
StdioConnectionParams(server_params=StdioServerParameters(command=, args=, env=), timeout=...)
```

MCP Toolbox for Databases: `from google.adk.tools.toolbox_toolset import ToolboxToolset`;
`ToolboxToolset(server_url, toolset_name=None, tool_names=None, ...)` (`toolbox-core` extra).
Built-ins: `google_search`, `url_context`, `enterprise_web_search`, `exit_loop`, `load_memory`,
`preload_memory`, `load_artifacts`, `get_user_choice`, `request_input`, `transfer_to_agent`.

## Runners, sessions, memory

```python
InMemoryRunner(agent=None, *, node=None, app_name=None, plugins=None, app: App | None = None)
Runner(*, app=None, app_name=None, agent=None, session_service: BaseSessionService, artifact_service=None,
       memory_service=None, credential_service=None, auto_create_session=False)
VertexAiSessionService(project=None, location=None, agent_engine_id=None, *, express_mode_api_key=None)
VertexAiMemoryBankService(project=None, location=None, agent_engine_id=None, *, credentials=None)
```

`DatabaseSessionService` needs the `db` extra (`sqlalchemy`), not installed in this repo.

## Workflow graphs (`google.adk.workflow`)

Exports: `Workflow`, `node`, `START`, `DEFAULT_ROUTE`, `Edge`, `FunctionNode`, `JoinNode`, `Node`,
`RetryConfig`, `NodeTimeoutError`. `node(node_like=None, *, name=None, rerun_on_resume=None,
retry_config: RetryConfig | None = None, timeout: float | None = None, parallel_worker=False,
max_parallel_workers=None, auth_config=None, parameter_binding='state' | 'node_input')`.
`Workflow(name=..., edges=[(START, a, b), (b, {"route": c, DEFAULT_ROUTE: d})])`.

## Evaluation objects

```python
EvalCase(eval_id, conversation: list[Invocation], conversation_scenario=None, session_input=None,
         creation_timestamp, rubrics=None, final_session_state=None)
Invocation(invocation_id, user_content, final_response, intermediate_data, creation_timestamp, rubrics, app_details)
IntermediateData(tool_uses, tool_responses, intermediate_responses)
SessionInput(app_name, user_id, session_id, state)
EvalConfig(criteria, custom_metrics, user_simulator_config, live_model_config)
AgentEvaluator.evaluate(agent_module, eval_dataset_file_path_or_dir, num_runs=2, agent_name=None,
                        initial_session_file=None, print_detailed_results=True, artifact_service=None,
                        output_file=None, app_name=None, eval_set_results_manager=None) -> None
AgentEvaluator.find_config_for_test_file(test_file) -> EvalConfig   # loads test_config.json beside the file
register_custom_metrics_from_config(eval_config, metric_evaluator_registry=None)  # google.adk.evaluation.metric_evaluator_registry
```

Prebuilt metric names: `tool_trajectory_avg_score, response_evaluation_score, response_match_score, safety_v1,
final_response_match_v2, rubric_based_final_response_quality_v1, hallucinations_v1,
rubric_based_tool_use_quality_v1, per_turn_user_simulator_quality_v1, multi_turn_task_success_v1,
multi_turn_trajectory_quality_v1, multi_turn_tool_use_quality_v1, rubric_based_multi_turn_trajectory_quality_v1`.

## CLI (2.9.0)

| Command | Notes |
|---|---|
| `adk web <agents_dir> --port 8000` | dev UI; `--session_service_uri`, `--memory_service_uri`, `--otel_to_cloud`, `--reload_agents`, `--default_llm_model` |
| `adk run <agent_dir>` | terminal chat |
| `adk api_server <agents_dir>` | FastAPI server (`/run_sse`, confirmation resume by `invocation_id`) |
| `adk eval <agent_dir> <evalset>[:case1,case2] --config_file_path <json> --print_detailed_results` | informational, exit code always 0 |
| `adk eval_set create \| add_eval_case --scenarios_file --session_input_file \| generate_eval_cases` | user-sim evalsets |
| `adk conformance record \| test` | baseline regression recordings |
| `adk optimize --sampler_config_file_path ...` | GEPA instruction optimisation |
| `adk deploy agent_engine \| cloud_run \| gke \| docker` | see agent-platform-runtime for the Agent Runtime flags |
| `adk create <app>` | scaffold: `__init__.py` (`from . import agent`) + `agent.py` (`root_agent`) |

`adk deploy agent_engine` (verified `--help`): `--project`, `--region`, `--display_name`, `--description`,
`--agent_engine_id` (update), `--otel_to_cloud`, `--adk_version` (defaults to the local version),
`--extra_packages` (repeatable), `--agent_engine_config_file` (`.agent_engine_config.json`), `--worker_pool`,
`--session_service_uri agentengine://<id>`, `--memory_service_uri`, `--artifact_service_uri gs://...`,
`--trigger_sources pubsub,eventarc`, `--trigger_oidc_audience`, `--trigger_oidc_service_accounts`,
`--temp_folder`. Deprecated (accepted, ignored): `--staging_bucket`, `--env_file`, `--requirements_file`,
`--adk_app`, `--adk_app_object`, `--trace_to_cloud`, `--absolutize_imports`, `--validate-agent-import`.
