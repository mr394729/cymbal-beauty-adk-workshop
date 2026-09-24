---
name: agent-platform-runtime
description: Agent Runtime on the Gemini Enterprise Agent Platform (formerly Vertex AI Agent Engine) with the google-cloud-aiplatform SDK. Use when deploying or updating an ADK App (AdkApp, agent_engines.create/update, requirements, extra_packages, service_account, env_vars with Secret Manager references), working with runtime revisions and traffic splits (canary, rollback, prune), sessions and Memory Bank, telemetry, agent identity, the deployment/*.py scripts, the release manifest, Cloud Build approval triggers, WIF for pipelines or the dev to preprod to prod promotion ladder. Not for writing the agent itself (see google-adk) or for generic gcloud, IAM and BigQuery recipes (see gcp-integration).
metadata:
  workshop: cymbal-beauty-adk-workshop
  version: "1.0"
  verified: "2026-09-12"
---

# Agent Runtime (Agent Platform) and promotion

The workshop deploys one engine per environment (`cymbal-store-ops-<namespace>-<env>`) in one project,
each under its own runtime service account, and promotes **the same commit and lock** through the ladder. Within
prod, new code is a new **revision** that starts at 0 % traffic; canary and rollback are traffic edits.
SDK verified: `google-cloud-aiplatform 1.165.1` (`vertexai.Client`, `vertexai.agent_engines.AdkApp`).

## When to use

- `uv run python deployment/release.py && uv run python deployment/deploy.py --env dev --release release.json`, `uv run python deployment/release.py && uv run python deployment/deploy.py --env dev --release release.json --dry-run`, or any change to `deployment/*.py` or `config/envs/*.yaml`.
- Reading or changing `cloudbuild/*.yaml` or `.github/workflows/*.yml`.
- Listing revisions, shifting traffic, rolling back, deleting zero-traffic revisions, smoke-testing a revision.
- Wiring Secret Manager values, sessions, Memory Bank or telemetry into a deployed agent.

## Facts that override older docs

- Product name: **Agent Runtime** on Gemini Enterprise Agent Platform; API resource is still
  `reasoningEngines`; docs moved from `vertex-ai/.../agent-engine` to
  `gemini-enterprise-agent-platform/scale/runtime/...`. `gcloud ai reasoning-engines` does not exist: SDK or REST.
- Wrap the production `App`: `AdkApp(app=app)` with `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true` in `env_vars` (not `enable_tracing=True`, which also copies message content into spans); `AdkApp(agent=root_agent)` still
  works but loses plugins and resumability. `AdkApp` init keywords: `app, agent, app_name, plugins,
  enable_tracing, session_service_builder, artifact_service_builder, memory_service_builder, instrumentor_builder`.
- Client: `vertexai.Client(project=, location="us-central1", http_options=HttpOptions(api_version="v1beta1"))`.
  Revisions and traffic splitting are **v1beta1** (Preview); `create`/`update` also work on `v1`.
- `client.agent_engines.create(agent=adk_app, config={...})` and
  `client.agent_engines.update(name=RESOURCE_NAME, agent=adk_app, config={...})` are keyword-only.
  `config` keys: `requirements` (list or `requirements_file`), `extra_packages`, `staging_bucket`,
  `display_name`, `description`, `env_vars`, `service_account`, `labels`, `min_instances`, `max_instances`,
  `resource_limits`, `container_concurrency`, `identity_type`, `traffic_config`, `agent_server_mode`.
- Secret references: `env_vars={"PARTNER_API_KEY": {"secret": "store-ops-dev-partner-api-key", "version": "3"}}`
  becomes `secret_env`; plain strings become `env`. Pin **version numbers** in `config/envs/*.yaml`, never
  `latest`. The Agent Platform service agent (`service-PROJECT_NUMBER@gcp-sa-aiplatform.iam.gserviceaccount.com`)
  needs `roles/secretmanager.secretAccessor` on each secret; a missing secret fails the deploy, no fallback.
- Versioned fields create a new immutable revision: package spec (extra packages, requirements), `env`/`secretEnv`,
  `minInstances`/`maxInstances`, resource limits, source code spec, identity type, class methods.
- Traffic: `update(name=, config={"traffic_config": {"traffic_split_manual": {"targets": [
  {"runtime_revision_name": REV, "percent": 90}, {"runtime_revision_name": NEW, "percent": 10}]}}})`;
  percentages must sum to 100 (`deployment/traffic.py` refuses otherwise). `traffic_split_always_latest: {}`
  is the default (dev/preprod). Revisions: `client.agent_engines.runtimes.revisions.list(name=ENGINE)`,
  `.get(name=REV)`, `.delete(name=REV)`; `.get(...).query(input=..., config={"class_method": ...})` probes one
  revision directly. Only zero-traffic revisions can be deleted; rollback is a traffic edit, not a build.
- Query a deployed ADK agent: `adk_app = client.agent_engines.get(name=RESOURCE_NAME)`, then
  `await adk_app.async_create_session(user_id=)` and `async for ev in adk_app.async_stream_query(user_id=, session_id=, message=)`.
- Sessions and Memory Bank are GA: `VertexAiSessionService(project, location, agent_engine_id)`,
  `VertexAiMemoryBankService(...)`; locally `adk web --session_service_uri agentengine://<id>`.
- Logs: `resource.type="aiplatform.googleapis.com/ReasoningEngine"` with `resource.labels.reasoning_engine_id`;
  log ids `reasoning_engine_stdout|stderr|build`. Traces: `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true` on the engine, `--otel_to_cloud` locally.
- Runtime identity: prefer a dedicated runtime service account per environment (`store-ops-<env>-runtime@`),
  granted only `bigquery.jobUser` + `dataViewer` on its dataset and `secretAccessor` on its secrets.
- `adk deploy agent_engine` current vs deprecated flags: see google-adk `skills/google-adk/references/adk-2x-api.md`.
  This repo deploys through `deployment/deploy.py` so the release manifest is produced every time.

## Repo map

| Path | Purpose |
|---|---|
| `deployment/deploy.py --env <env> --release release.json [--dry-run]` | create or update the engine (`extra_packages=["agents"]` + exported lock); finds the engine by its labels `app=cymbal-store-ops`, `ns=<WORKSHOP_NAMESPACE>`, `env` (or `AGENT_ENGINE_ID`); writes the local record `deployment/deployment_info.<namespace>.<env>.json` |
| `deployment/traffic.py list \| promote --env prod --revision <r> --percent 10 \| rollback --to <r> \| prune` | manual traffic split on prod; every change names its revision |
| `deployment/smoke.py --env <env> [--revision <rev>]` | one golden query, asserts an `inventory_excellence` call and the fixture count, exit 1 otherwise |
| `deployment/teardown.py`, `deployment/iam/setup_wif.sh`, `deployment/iam/setup_cloudbuild_triggers.sh` | teardown, WIF + service accounts, approval triggers |
| `deployment/AGENTS.md` | which of these an agent may run and where |
| `agents/cymbal_store_ops/config/envs/{dev,preprod,prod}.yaml` | only per-env differences (engine id, SA, min_instances, traffic mode, approvals, dataset, secret refs) |
| `release.json` (generated, gitignored) | git sha, `build/requirements.txt` sha256, prompt/config digests, ADK version, `DATA_VERSION`, model and secret versions per env |
| `cloudbuild/{ci,deploy,promote,rollback}.yaml`, `.github/workflows/` | the same scripts run by both CI systems |

## Recipes

### Deploy (what `deploy.py` does)

```python
import vertexai
from google.genai.types import HttpOptions
from vertexai.agent_engines import AdkApp
from agents.cymbal_store_ops.agent import create_app

client = vertexai.Client(project=PROJECT, location="us-central1", http_options=HttpOptions(api_version="v1beta1"))
config = {
    "display_name": cfg["agent_engine"]["display_name"],
    "requirements": "build/requirements.txt",                 # uv export --frozen (a file path is accepted)
    "extra_packages": ["agents"],                              # the package directory, relative to the cwd
    "staging_bucket": f"gs://{PROJECT}-cymbal-store-ops-staging",
    "gcs_dir_name": f"agent_engine/{NAMESPACE}/store-ops-{env}",   # your own folder: the default is one shared agent_engine/ for the whole project
    "service_account": f"{cfg['agent_engine']['service_account']}@{PROJECT}.iam.gserviceaccount.com",
    "env_vars": {"GOOGLE_GENAI_USE_VERTEXAI": "TRUE", "STORE_OPS_ENV": env,   # never GOOGLE_CLOUD_LOCATION: the runtime owns it
                 **{k: {"secret": v["secret"], "version": str(v["version"])} for k, v in cfg["secret_env_vars"].items()}},
    "labels": {"env": env, "git-sha": sha[:12]},
    "min_instances": cfg["agent_engine"]["min_instances"],
}
app = AdkApp(app=create_app())   # env_vars: GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true
engine_id = cfg["agent_engine"]["agent_engine_id"]
if engine_id:
    remote = client.agent_engines.update(name=f"projects/{PROJECT}/locations/us-central1/reasoningEngines/{engine_id}",
                                         agent=app, config=config)
else:
    remote = client.agent_engines.create(agent=app, config=config)
    print("add to config/envs/%s.yaml: agent_engine_id: %s" % (env, remote.api_resource.name.rsplit('/', 1)[-1]))
```

### List revisions and split traffic (what `traffic.py` does)

```python
engine = f"projects/{PROJECT}/locations/us-central1/reasoningEngines/{engine_id}"
revs = list(client.agent_engines.runtimes.revisions.list(name=engine))
for r in revs: print(r.api_resource.name, r.api_resource.state, r.api_resource.create_time)
client.agent_engines.update(name=engine, config={"traffic_config": {"traffic_split_manual": {"targets": [
    {"runtime_revision_name": old, "percent": 90}, {"runtime_revision_name": new, "percent": 10}]}}})
# rollback = the same call with {old: 100}; prune = revisions.delete(name=zero_traffic_rev)
```

Poll the returned operation to completion, then re-read the engine and assert the observed traffic config.

### Probe one revision directly

```python
rev = client.agent_engines.runtimes.revisions.get(name=new)
out = rev.query(input={"user_id": "smoke", "message": "Is Lumière Hydra Cream in stock near Naperville?"},
                config={"class_method": "stream_query"})
```

### The promotion ladder in one paragraph

Each deployment build writes its own manifest for the selected checkout (`release.py`; the approver compares its
commit and digests with the earlier passing evidence), deploy dev, smoke, **approval**, deploy
preprod, smoke + `remote_eval.py`, **approval**, prod candidate at 0 %, `smoke.py --revision`, promote 10 %,
direct revision probes, **approval**, promote 100 %, prune. Approvals live in Cloud
Build (`--require-approval` triggers, `gcloud alpha builds approve`); GitHub Actions is PR checks only. Details in
[references/promotion.md](references/promotion.md).

## Gotchas

- Deploys take 5 to 10 minutes; pre-create the prod candidate before a demo, then only shift traffic live.
- `extra_packages` entries are tarred with the path you pass and unpacked under `/code`, so pass `"agents"`
  from the repo root (the docs' shape); a path like `dist/x/agents` lands at `/code/dist/x/agents` and
  `import agents` fails at container start. A top-level name that shadows an installed dependency also breaks imports.
- Do not set `GOOGLE_CLOUD_LOCATION` (or `GOOGLE_CLOUD_PROJECT`) in `env_vars`: the runtime sets them to its own
  region and project. Pin the model location on the client instead (`VertexGemini` in `agents/cymbal_store_ops/agent.py`).
- Clients (BigQuery, Secret Manager) must be created at runtime inside tools, never at import
  time, or the pickled `AdkApp` carries credentials and stale state.
- Changing `env_vars` creates a revision; with `traffic_split_manual` the new revision gets **no** traffic
  until you say so. With `traffic_split_always_latest` it takes 100 % immediately.
- `remote.delete(force=True)` removes sessions and memories too; teardown asks for `YES=1`.
- Run one traffic-changing build per engine at a time; two promotions in flight corrupt the traffic table. This
  repository does not configure a shared promotion lock.
- Per-env deployer identities: each `cicd-deployer-<env>@` can act as its environment's runtime account; its
  project-wide Vertex AI permissions do not demonstrate complete isolation from other environments' engines. The
  evaluator identity cannot deploy.

## References

- [references/deploy-and-revisions.md](references/deploy-and-revisions.md), config keys, revisions, sessions, memory, telemetry
- [references/promotion.md](references/promotion.md), ladder, Cloud Build approvals, WIF, manifest, rollback
- Deploy an agent: https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/deploy-an-agent
- Use an ADK agent: https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-an-adk-agent
- Revisions and traffic: https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-revisions-and-traffic
- Manage deployed agents: https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-deployed-agents
- Sessions: https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sessions ; Memory Bank: https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank
- Logging, tracing, monitoring: https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/logging , https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/tracing , https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/monitoring
- Agent identity: https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/agent-identity
- ADK deploy docs: https://adk.dev/deploy/agent-runtime/ , https://adk.dev/deploy/agent-runtime/deploy/ , https://adk.dev/deploy/agent-runtime/test/
- Cloud Build approvals: https://docs.cloud.google.com/build/docs/securing-builds/gate-builds-on-approval
- WIF for pipelines: https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines
