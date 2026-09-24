# Agent Runtime: deploy, revisions, sessions, memory, telemetry (verified 2026-09-12)

SDK: `google-cloud-aiplatform[agent_engines,adk]==1.165.1` in the repo lock. Types below come from
`vertexai.types` and were printed by introspection.

## AgentEngineConfig keys

`http_options, staging_bucket, requirements, display_name, description, gcs_dir_name, extra_packages,
env_vars, service_account, identity_type, context_spec, psc_interface_config, min_instances, max_instances,
resource_limits, container_concurrency, encryption_spec, labels, agent_server_mode, class_methods,
source_packages, developer_connect_source, entrypoint_module, entrypoint_object, requirements_file,
agent_framework, python_version, build_options, image_spec, agent_config_source, container_spec,
agent_gateway_config, keep_alive_probe, traffic_config, build_config`.

`env_vars` accepts a dict whose values are either strings (plain `env`) or `{"secret": SECRET_ID,
"version": "N"}` (`secret_env`, type `SecretEnvVar(name, secret_ref=SecretRef(secret, version))`).
Passing anything but a dict raises `TypeError`.

## Traffic config types

```text
ReasoningEngineTrafficConfig            {traffic_split_always_latest: {}} | {traffic_split_manual: {targets: [...]}}
ReasoningEngineTrafficConfigTrafficSplitManualTarget   {runtime_revision_name: str, percent: int}
```

Revision resource name: `projects/P/locations/L/reasoningEngines/ID/runtimeRevisions/REV`.
`ReasoningEngineRuntimeRevision` fields: `name, state (ACTIVE | DEPRECATED), create_time, spec`.
`client.agent_engines.runtimes.revisions.list(name=ENGINE)` yields `AgentEngineRuntimeRevision` objects
(`.api_resource` holds the fields, `.query(...)` runs a class method on that revision).

## Two ways to deploy

| | `deployment/deploy.py` (SDK) | `adk deploy agent_engine` |
|---|---|---|
| Artifact | `extra_packages=["agents"]` + `build/requirements.txt` (`uv export --frozen`) | source folder packaged by the CLI |
| Manifest | writes `release.json` and `deployment_info.<namespace>.<env>.json`; labels the engine `app`, `ns`, `env` | none |
| Config | `config/envs/<env>.yaml` | flags + `.agent_engine_config.json` |
| Use in this repo | dev via `uv run python deployment/release.py && uv run python deployment/deploy.py --env dev --release release.json`; preprod/prod via pipelines only | quickstarts and ad-hoc experiments |

CLI example (attendee experiments):

```bash
uv run adk deploy agent_engine --project "$GOOGLE_CLOUD_PROJECT" --region us-central1 \
  --display_name quickstart-hello --otel_to_cloud quickstarts/01-hello-tool-agent
# update later: add --agent_engine_id <id>
```

## Querying and sessions

```python
adk_app = client.agent_engines.get(name=RESOURCE_NAME)
session = await adk_app.async_create_session(user_id="u1")
async for event in adk_app.async_stream_query(user_id="u1", session_id=session["id"], message="Hi"):
    print(event)          # dicts with author, content.parts, id
sessions = await adk_app.async_list_sessions(user_id="u1")
await adk_app.async_delete_session(user_id="u1", session_id=session["id"])
```

Sessions API without ADK: `client.agent_engines.sessions.create(name=ENGINE, user_id=)`,
`client.agent_engines.sessions.events.append(...)`. Memory Bank: `client.agent_engines.memories.generate(
name=ENGINE, vertex_session_source={"session": SESSION_NAME}, scope={"user_id": ...})`,
`.retrieve(name=ENGINE, scope={...})`, `.delete(name=MEMORY)`. In an ADK agent use `preload_memory` /
`load_memory` tools with `VertexAiMemoryBankService`.

Local development against the deployed session store:

```bash
uv run adk web agents --session_service_uri agentengine://<engine_id> --memory_service_uri agentengine://<engine_id>
```

## Telemetry

- `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true` in `env_vars` exports OpenTelemetry spans to Cloud Trace without message content (`enable_tracing=True` would force `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=true`); for `adk web` use
  `--otel_to_cloud`. Environment knobs on the runtime: `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY` and the
  standard `OTEL_*` variables.
- Logs Explorer filter for one engine:

```text
resource.type="aiplatform.googleapis.com/ReasoningEngine"
resource.labels.reasoning_engine_id="ENGINE_ID"
severity>=WARNING
```

- Log ids: `reasoning_engine_stdout`, `reasoning_engine_stderr`, `reasoning_engine_build` (deploy-time).
- Other exporters (Langfuse, Phoenix, Datadog) attach through the same OTel pipeline; see adk.dev integrations.

## Identity

- `service_account` in the config is the **runtime** identity; grant it only what the tools need
  (`roles/bigquery.jobUser`, `roles/bigquery.dataViewer` on its dataset, `roles/secretmanager.secretAccessor`).
- The deployer needs `roles/aiplatform.user`, `roles/iam.serviceAccountUser` on the runtime SA,
  `roles/storage.objectAdmin` on the staging bucket, `roles/serviceusage.serviceUsageConsumer`.
- The evaluator identity is read-only (`bigquery.dataViewer` on dev, `aiplatform.user`) and cannot deploy or
  shift traffic; `tests/iam/` proves it under impersonation.
- Agent Identity (SPIFFE, managed workload identity) is GA; `identity_type` selects it. The workshop uses the
  explicit runtime SA for readability.

## Costs and cleanup

- `min_instances: 0` everywhere except prod (1) keeps idle cost near zero; delete preprod/prod after the event.
- `uv run python deployment/teardown.py --env <env> --yes && bash data/teardown.sh --env <env> --yes` deletes the engine (force, including sessions) and the datasets.
- Only zero-traffic revisions can be deleted; `traffic.py prune` does that after a successful 100 % promotion.
