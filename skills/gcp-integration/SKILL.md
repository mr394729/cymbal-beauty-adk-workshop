---
name: gcp-integration
description: Working with Google Cloud from this repo without friction (gcloud, bq, gsutil, ADC and quota project, 401/403 self-diagnosis, least-privilege IAM and impersonation, Workload Identity Federation, Secret Manager, read-only BigQuery with job labels and byte limits, Cloud Build, Artifact Registry, Logs Explorer filters, cost guardrails). Use when a command fails with a permission or auth error, when you need a gcloud or bq recipe, when granting or checking roles, or when adding a cloud call to a script. Not for the Agent Runtime deploy and promotion flow (see agent-platform-runtime) or for Gemini SDK calls (see gemini-genai). For driving gcloud and bq themselves (output shaping, read before change, namespace-scoped cleanup) use gcloud-cli.
metadata:
  workshop: cymbal-beauty-adk-workshop
  version: "1.0"
  verified: "2026-09-12"
allowed-tools: Bash Read
---

# Google Cloud integration

The workshop runs in one project, often shared by a room of attendees: one dataset per namespace and environment
(`cymbal_beauty_<namespace>_<env>`), one engine per namespace and environment, and a small set of shared service
accounts (`docs/SHARED_PROJECT.md`). Almost every failure an attendee hits is one of: no ADC, wrong quota project,
wrong location, missing role, disabled API. Diagnose in that order; never work around with a broader role.

## When to use

- Any `401`, `403`, `PERMISSION_DENIED`, `Reauthentication`, `quota project` or `API not enabled` message.
- Adding a `gcloud`, `bq`, `gsutil`, Secret Manager, Cloud Build or Logs Explorer step to a script or doc.
- Granting a role, creating a service account, impersonating one, or setting up WIF for a CI system.
- Checking that a BigQuery call is read-only, labelled and bounded before it ships in a tool.

## Facts that override older docs

- The workshop identity model: attendee (project Owner is **not** assumed; roles in `docs/IAM_MATRIX.md`),
  runtime SA per env `store-ops-<env>-runtime@`, evaluator `cicd-evaluator@` (read-only), deployer per env
  `cicd-deployer-<env>@`, approver (human). Validate with impersonation, never with Owner ADC.
- ADC lives in `~/.config/gcloud/application_default_credentials.json` after
  `gcloud auth application-default login`; the quota project must be set
  (`gcloud auth application-default set-quota-project PROJECT`) or client libraries fail with 403
  `SERVICE_DISABLED` / "quota project" errors even when the role is right.
- Gemini 3.x is served from `GOOGLE_CLOUD_LOCATION=global`; Agent Runtime and the staging bucket live in
  `us-central1`; BigQuery datasets are multi-region `US`. Three locations, on purpose.
- APIs required locally: `aiplatform.googleapis.com`, `bigquery.googleapis.com`; `uv run python deployment/release.py && uv run python deployment/deploy.py --env dev --release release.json` also needs
  `storage` and `iamcredentials` (plus `secretmanager` when the environment declares secrets), which
  `scripts/check_env.py` reports as WARN. `deployment/iam/setup_wif.sh` enables the full workshop set.
- Every workshop resource carries `WORKSHOP_NAMESPACE` (`uv run python scripts/namespace.py` writes it into `.env`): dataset
  `cymbal_beauty_<namespace>_<env>`, engine `cymbal-store-ops-<namespace>-<env>` labelled `ns=<namespace>`, BigQuery
  job label `ns=<namespace>`. Namespaces are naming, not an access boundary: the runtime SAs and the staging bucket
  are shared.
- BigQuery read-only by construction: `WriteMode.BLOCKED`, `maximum_bytes_billed` (100 MB per query in
  `config/envs/*.yaml`), `max_query_result_rows`, `job_labels` (lowercase keys) and a `SELECT`-only guard.
  Evidence: `INFORMATION_SCHEMA.JOBS_BY_USER` for your own jobs, `JOBS_BY_PROJECT` for everyone's (needs `bigquery.jobs.listAll`; labels, `referenced_tables`) and `bq ls -j`. Dataplex
  lineage does **not** record plain `SELECT` reads; use `referenced_tables`.
- Write isolation: the runtime SA `store-ops-<env>-runtime@` has dataset `READER` on
  `cymbal_beauty_<namespace>_<env>` and `bigquery.dataEditor` on the `store_tasks` table only, so the agent's one
  write path cannot touch inventory or products. Authorized views or row-level policies are the production pattern
  for per-store access.
- Secret Manager: reference secrets by **version number** in config; grant `roles/secretmanager.secretAccessor`
  per secret to the identity that reads it (for Agent Runtime that is the Agent Platform service agent
  `service-PROJECT_NUMBER@gcp-sa-aiplatform.iam.gserviceaccount.com` plus the runtime SA).
- WIF: one pool, one provider per CI system, attribute conditions on stable ids, bind
  `roles/iam.workloadIdentityUser` to the deployer SA. Fork PRs never get credentials.
- Cloud Build approvals: triggers created with `--require-approval` wait for
  `gcloud alpha builds approve BUILD_ID --location REGION` from a `roles/cloudbuild.approver` (the GA track has no
  `approve`; the console's **Approve** button does the same).
- Official Google skills for coding agents exist (Authentication, gcloud, BigQuery, Cloud Run, IAM
  Troubleshooter) at https://github.com/google/skills ; they are complementary and use different names.

## Repo map

| Path | Purpose |
|---|---|
| `scripts/check_env.py --stage prereqs\|ready` | loud pre-flight: tools, ADC, project, APIs, location, model, datasets, fixtures |
| `scripts/check_adc.sh` (this skill) | who am I, which quota project, does a token mint, is the project reachable |
| `scripts/whoami_iam.sh` (this skill) | roles the active identity holds on the project (+ `--sa` for a service account) |
| `deployment/iam/setup_wif.sh`, `deployment/iam/setup_cloudbuild_triggers.sh` | idempotent IAM, WIF, secrets, triggers |
| `docs/IAM_MATRIX.md`, `tests/iam/` | principal, operation, resource matrix and the negative tests |
| `data/load.sh` | `bq mk`, `bq load --replace`, row-count assertion |
| `.env.example` | `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION=global`, `AGENT_ENGINE_LOCATION`, `BQ_LOCATION`, `WORKSHOP_NAMESPACE` |
| `uv run python scripts/namespace.py`, `uv run python scripts/resources.py`, `uv run python scripts/resources.py --delete --yes` | set your namespace; list or delete every resource that carries it |

## Recipes

### Self-diagnose an auth or permission error

```bash
bash skills/gcp-integration/scripts/check_adc.sh                 # identity, quota project, token, project
bash skills/gcp-integration/scripts/whoami_iam.sh                 # roles on the project
bash skills/gcp-integration/scripts/whoami_iam.sh --sa store-ops-dev-runtime@$GOOGLE_CLOUD_PROJECT.iam.gserviceaccount.com
```

| Symptom | Likely cause | Fix |
|---|---|---|
| `Reauthentication is needed` / `invalid_grant` | ADC expired | `gcloud auth application-default login` |
| 403 `... has not been used in project ... or it is disabled` | API disabled or wrong quota project | `gcloud services enable <api> --project $P`; `gcloud auth application-default set-quota-project $P` |
| 403 `PERMISSION_DENIED` on a resource | missing role on that resource (dataset, secret, bucket) | grant the narrowest role on the resource, not the project |
| 404 from `generate_content` | regional location for a Gemini 3.x model | `GOOGLE_CLOUD_LOCATION=global` |
| 403 `iam.serviceAccounts.actAs` | deployer lacks `roles/iam.serviceAccountUser` on the runtime SA | bind it on the SA, not the project |
| `bq` works but Python fails | different identities (`gcloud auth` vs ADC) | compare `gcloud auth list` with `check_adc.sh` |
| 429 `RESOURCE_EXHAUSTED` | model quota in `global` | check the quotas page; do not switch models silently |

### Impersonate a service account to test least privilege

```bash
gcloud auth print-access-token --impersonate-service-account cicd-evaluator@$P.iam.gserviceaccount.com >/dev/null
bq --project_id=$P query --use_legacy_sql=false --format=json \
  "SELECT COUNT(*) n FROM \`$P.cymbal_beauty_${WORKSHOP_NAMESPACE}_dev.products\`"     # uses gcloud creds; for ADC set
export GOOGLE_CLOUD_QUOTA_PROJECT=$P CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT=cicd-evaluator@$P.iam.gserviceaccount.com
```

Python: `google.auth.impersonated_credentials.Credentials(source_credentials, target_principal, target_scopes)`.

### Grant the runtime SA exactly what a tool needs

```bash
gcloud projects add-iam-policy-binding $P --member serviceAccount:$SA --role roles/bigquery.jobUser --condition=None
bq add-iam-policy-binding --member serviceAccount:$SA --role roles/bigquery.dataViewer $P:cymbal_beauty_${WORKSHOP_NAMESPACE}_dev
gcloud secrets add-iam-policy-binding store-ops-dev-partner-api-key --member serviceAccount:$SA \
  --role roles/secretmanager.secretAccessor --project $P
```

### Read-only BigQuery job with labels and a byte cap (plain client)

```python
from google.cloud import bigquery
client = bigquery.Client(project=P)
job = client.query(sql, job_config=bigquery.QueryJobConfig(
    query_parameters=[bigquery.ScalarQueryParameter("city", "STRING", city)],
    maximum_bytes_billed=100 * 1024 * 1024, labels={"adk_agent": "cymbal_store_ops", "env": env}))
rows = [dict(r) for r in job.result(max_results=50)]
```

### Evidence: what did the agent run?

```bash
bq ls -j --max_results 20 --project_id $P            # recent jobs with labels
```

```sql
SELECT job_id, user_email, labels, referenced_tables, total_bytes_processed
FROM `region-us`.INFORMATION_SCHEMA.JOBS_BY_USER   -- JOBS_BY_PROJECT for every principal's jobs (bigquery.jobs.listAll)
WHERE creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)
```

### Secrets

```bash
printf '%s' "$VALUE" | gcloud secrets create store-ops-dev-partner-api-key --data-file=- --project $P   # first time
printf '%s' "$VALUE" | gcloud secrets versions add store-ops-dev-partner-api-key --data-file=- --project $P
gcloud secrets versions list store-ops-dev-partner-api-key --project $P      # pin the number in envs/<env>.yaml
```

### Logs Explorer filters

```text
resource.type="aiplatform.googleapis.com/ReasoningEngine" resource.labels.reasoning_engine_id="ID" severity>=ERROR
resource.type="bigquery_project" protoPayload.methodName="jobservice.jobcompleted" protoPayload.authenticationInfo.principalEmail="store-ops-dev-runtime@P.iam.gserviceaccount.com"
resource.type="build" labels."build_trigger_id"="TRIGGER_ID"
```

### Cost guardrails

Budget alert (`gcloud billing budgets create`), `maximum_bytes_billed` on every query, `min_instances: 0`
outside prod, `max_query_result_rows`, delete what you created after the workshop (`uv run python scripts/resources.py --delete --yes`),
`bq show --format=prettyjson $P:cymbal_beauty_${WORKSHOP_NAMESPACE}_dev` to confirm the `data_version` label before
reloading.

## Gotchas

- `gcloud auth login` and ADC are different credentials; `bq` uses the former, Python the latter.
- Project-level `roles/bigquery.dataViewer` lets an identity read every attendee's dataset; grant at dataset level.
- `--condition=None` avoids the interactive prompt when the project already has conditional bindings.
- Service account keys are never created in this repo (`*.key.json` is gitignored and WIF replaces them).
- Cloud Shell has `gcloud`, `bq`, `uv` after `uv sync --all-extras`; Python 3.12 is required.
- `INFORMATION_SCHEMA.JOBS` is regional: query it as `` `region-us`.INFORMATION_SCHEMA.JOBS_BY_USER `` (own jobs, `bigquery.jobs.list`) or `` `region-us`.INFORMATION_SCHEMA.JOBS_BY_PROJECT `` (all jobs, `bigquery.jobs.listAll`).

## References

- [references/auth-and-iam.md](references/auth-and-iam.md), ADC, impersonation, roles matrix, WIF setup
- [references/bigquery-and-ops.md](references/bigquery-and-ops.md), BigQuery governance, Cloud Build, Artifact Registry, logging, budgets
- ADC: https://docs.cloud.google.com/docs/authentication/provide-credentials-adc , troubleshooting: https://docs.cloud.google.com/docs/authentication/troubleshoot-adc
- Quota project: https://docs.cloud.google.com/docs/quotas/quota-project
- IAM roles and troubleshooting: https://docs.cloud.google.com/iam/docs/understanding-roles , https://docs.cloud.google.com/iam/docs/troubleshooting-access
- Impersonation: https://docs.cloud.google.com/iam/docs/service-account-impersonation
- WIF: https://docs.cloud.google.com/iam/docs/workload-identity-federation , https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines
- Secret Manager: https://docs.cloud.google.com/secret-manager/docs/creating-and-accessing-secrets
- BigQuery: https://docs.cloud.google.com/bigquery/docs/information-schema-jobs , https://docs.cloud.google.com/bigquery/docs/labels-intro , https://docs.cloud.google.com/bigquery/docs/best-practices-costs , https://docs.cloud.google.com/bigquery/docs/authorized-views
- Cloud Build approvals: https://docs.cloud.google.com/build/docs/securing-builds/gate-builds-on-approval
- Logging query language: https://docs.cloud.google.com/logging/docs/view/logging-query-language
- Google's own skills: https://github.com/google/skills
