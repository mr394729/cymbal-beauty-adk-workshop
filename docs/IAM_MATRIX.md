# IAM matrix

Principal → operation → resource. Owner or Editor is never the baseline; every identity below is created by
`deployment/iam/setup_wif.sh` with exactly these grants.

| Principal | Operation | Resource | Role |
|---|---|---|---|
| attendee (person), shared project | run labs, load their namespaced data, deploy their dev engine | project (group granted by `setup_wif.sh --attendee-group`) | `roles/aiplatform.user`, `roles/bigquery.jobUser`, `roles/bigquery.user` (creates `cymbal_beauty_<namespace>_*` and owns what it creates), `roles/serviceusage.serviceUsageConsumer`, `roles/pubsub.editor`, `roles/logging.viewer`, `roles/cloudtrace.user`, `roles/agentregistry.viewer`, `roles/discoveryengine.admin` (creates and deletes the SOP data store; Editor cannot create data stores); `roles/iam.serviceAccountUser` on `store-ops-dev-runtime@`; `objectAdmin` on the staging bucket; on the staging bucket `objectAdmin` + `legacyBucketReader` (a dev deploy from a laptop reads the bucket, then uploads) |
| `store-ops-<env>-runtime@` (one identity per environment) | call Gemini, sessions, memory, traces, SOP search and use the API quota project | project | `roles/aiplatform.user`, `roles/serviceusage.serviceUsageConsumer`, `roles/cloudtrace.agent`, `roles/logging.logWriter`, `roles/monitoring.metricWriter`, `roles/discoveryengine.viewer`, `roles/modelarmor.user` (when `MODEL_ARMOR_TEMPLATE` is set) |
| `store-ops-<env>-runtime@` | run queries | project | `roles/bigquery.jobUser` |
| `store-ops-<env>-runtime@` | read catalog, stores, inventory, roster, BOPIS, traffic, shrink, feedback, coaching | dataset `cymbal_beauty_<namespace>_<env>` | `roles/bigquery.dataViewer` (dataset `READER` entry) |
| `store-ops-<env>-runtime@` | create or delegate a task | table `store_tasks` only | `roles/bigquery.dataEditor` (table-level) |
| `store-ops-<env>-runtime@` | read its secrets | each secret `store-ops-<env>-*` | `roles/secretmanager.secretAccessor` (per secret) |
| `cicd-evaluator@` | eval gate: model calls + dev data | project + `cymbal_beauty_<namespace>_dev` | custom role `cymbalModelCaller` (`aiplatform.endpoints.predict` only, so it cannot deploy), `roles/bigquery.jobUser`, dataset `READER` |
| `cicd-deployer-<env>@` | create/update the engine, shift traffic | project | `roles/aiplatform.user`, `roles/serviceusage.serviceUsageConsumer` |
| `cicd-deployer-<env>@` | upload the package | staging bucket | `objectAdmin` + `legacyBucketReader` (the SDK reads the bucket before it uploads) on `gs://<project>-cymbal-store-ops-staging` |
| `cicd-deployer-<env>@` | deploy *as* the runtime identity | `store-ops-<env>-runtime@` | `roles/iam.serviceAccountUser` |
| Agent Runtime (formerly Agent Engine) service agent | run the engine as the runtime SA | `store-ops-<env>-runtime@` | `roles/iam.serviceAccountUser` |
| Discovery Engine service agent (Gemini Enterprise) | invoke the engine on behalf of users | project | `roles/aiplatform.user` |
| GitHub PR workflows (WIF `github-oidc`, this repo only) | impersonate | `cicd-evaluator@` | `roles/iam.workloadIdentityUser` |
| approver (person) | approve preprod / prod builds | Cloud Build triggers | `roles/cloudbuild.approver` |

Negative expectations (checked by `tests/iam/test_negative_iam.py`, live, via impersonation):
the runtime identity cannot write to `products` or `store_inventory` (only `store_tasks` is writable); `cicd-evaluator@`
cannot create or update an engine; `cicd-deployer-dev@` cannot read a prod secret.
