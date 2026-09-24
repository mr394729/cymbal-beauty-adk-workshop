# BigQuery governance, Cloud Build, Artifact Registry, logging, cost

## BigQuery, read-only by construction

Layers, all present in the running example:

1. **Identity**: runtime SA has dataset `READER` on `cymbal_beauty_<namespace>_<env>` (dataset-level access entry).
2. **Toolset**: `BigQueryToolConfig(write_mode=WriteMode.BLOCKED)`; BLOCKED = dry run, non-SELECT statement
   types are refused before any bytes are billed.
3. **Guard**: `agents/cymbal_store_ops/tools/sql_guard.py::assert_select_only(sql, table_prefix)` in the
   `before_tool_callback`: strips comments and literals, rejects `;`, first token must be `SELECT`/`WITH`,
   denies `SET/USE/CALL/EXPLAIN/DESCRIBE/SHOW`, rejects `INFORMATION_SCHEMA`, every table must start with the prefix.
4. **Budget**: `maximum_bytes_billed` (100 MB), `max_query_result_rows` (50), `statement_timeout_s` (60).
5. **Labels**: `job_labels={"adk_agent": "cymbal_store_ops", "env": env, "ns": namespace}`; the domain-tool backend
   adds `data_backend=bigquery` and `tool=<tool name>`, and ADK's `BigQueryToolset` adds its automatic
   `adk-bigquery-tool=<tool_name>` label. Keys lowercase; never start with `adk-bigquery-`.

Evidence queries:

```sql
-- what the agent ran (labels, tables, bytes)
SELECT creation_time, user_email, statement_type, total_bytes_processed, labels, referenced_tables
FROM `region-us`.INFORMATION_SCHEMA.JOBS_BY_USER   -- JOBS_BY_PROJECT for every principal's jobs (bigquery.jobs.listAll)
WHERE creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)
  AND EXISTS (SELECT 1 FROM UNNEST(labels) WHERE key = 'adk_agent')
ORDER BY creation_time DESC;
```

```bash
bq ls -j --max_results 20 --project_id $P
bq show --format=prettyjson -j <job_id> | python3 -c 'import json,sys; j=json.load(sys.stdin); print(j["configuration"]["labels"], j["statistics"]["query"].get("referencedTables"))'
```

Write isolation: the runtime identity holds `dataViewer` on the dataset and `dataEditor` on `store_tasks` only,
so the one write path (`create_store_task`, `delegate_task`) cannot touch inventory or products even if a prompt
asks it to. In production, put per-store row access behind an authorized view or row-level access policies.

Parameterised queries: `bigquery.ScalarQueryParameter("city", "STRING", value)` and `@city` in SQL; `bq query
--parameter=city:STRING:Naperville`. Never format user text into SQL.

Dataset bookkeeping: `bq mk --dataset --location=US --label data_version:<v> --label env:<env> --label ns:<namespace>`,
`bq load --replace --source_format=NEWLINE_DELIMITED_JSON`,
`bq show --format=prettyjson $P:cymbal_beauty_${WORKSHOP_NAMESPACE}_dev`.

## Cloud Build

```bash
gcloud builds submit --config cloudbuild/ci.yaml --project $P --substitutions _NAMESPACE=$WORKSHOP_NAMESPACE .
gcloud builds list --project $P --limit 5
gcloud alpha builds approve BUILD_ID --project $P --location us-central1   # approval-gated triggers; alpha track only
gcloud builds triggers list --project $P
```

Trigger facts (`deployment/iam/setup_cloudbuild_triggers.sh`): names start with the facilitator's namespace
(`<namespace>-ci`, `<namespace>-deploy-dev`, …); `--require-approval` on the preprod and prod triggers;
`--service-account` per trigger = the env's deployer SA (`cicd-evaluator` for CI);
`--substitutions _NAMESPACE,_ENV,_PERCENT`; concurrency 1 per engine; private worker
pools only when VPC-SC requires them (`adk deploy agent_engine --worker_pool`). Logs: `resource.type="build"`.

## Artifact Registry

The workshop ships the `agents/` package through Cloud Storage staging (`extra_packages`), not a container image. The
Cloud Run and GKE deployments need an image:

```bash
gcloud artifacts repositories create agents --repository-format=docker --location=us-central1 --project $P
gcloud builds submit --tag us-central1-docker.pkg.dev/$P/agents/cymbal-store-ops:$SHA .
```

## Logs Explorer

| Need | Filter |
|---|---|
| Errors from one engine | `resource.type="aiplatform.googleapis.com/ReasoningEngine" resource.labels.reasoning_engine_id="ID" severity>=ERROR` |
| Build output | `logName:"reasoning_engine_build" resource.labels.reasoning_engine_id="ID"` |
| BigQuery jobs by a runtime SA | `resource.type="bigquery_project" protoPayload.authenticationInfo.principalEmail="store-ops-dev-runtime@P.iam.gserviceaccount.com"` |
| Who accessed a secret | `resource.type="secretmanager.googleapis.com/Secret" protoPayload.methodName="google.cloud.secretmanager.v1.SecretManagerService.AccessSecretVersion"` (data access logs must be enabled) |
| Cloud Build trigger runs | `resource.type="build" labels."build_trigger_id"="TRIGGER_ID"` |

`gcloud logging read '<filter>' --project $P --limit 50 --format=json` for scripts.

## Cost guardrails and quotas

- Budget: `gcloud billing budgets create --billing-account=ACCOUNT --display-name=workshop --budget-amount=100USD --threshold-rule=percent=0.5 --threshold-rule=percent=0.9`.
- BigQuery: `maximum_bytes_billed`, small datasets (about 44,000 rows across twelve tables per namespace and
  environment), `US` multi-region.
- Agent Runtime: `min_instances: 0` except prod; delete engines and revisions after the event.
- Gemini: quota is per model per location; `global` has its own limits; check the quotas page before a room
  of 30 attendees runs evals with `num_samples: 3` judges.
- Teardown: `uv run python scripts/resources.py --delete --yes` removes everything in your namespace (engines, datasets, SOP data store,
  Pub/Sub topic); `uv run python deployment/teardown.py --env <env> --yes && bash data/teardown.sh --env <env> --yes` removes one environment's engine and dataset.
