# Auth and IAM for the workshop

## Credentials, three kinds

| Kind | Set by | Used by | Check |
|---|---|---|---|
| gcloud user credentials | `gcloud auth login` | `gcloud`, `bq`, `gsutil` | `gcloud auth list` |
| Application Default Credentials (ADC) | `gcloud auth application-default login` (+ `set-quota-project`) | Python clients, ADK, `google-genai`, `scripts/check_env.py` | `scripts/check_adc.sh` |
| Federated (WIF) | CI job exchanges an OIDC token for a short-lived SA token | Cloud Build, GitHub Actions, any CI that issues OIDC tokens | a read-only step (`bq ls`) before any deploy |

Never create service-account keys for this repo. `GOOGLE_APPLICATION_CREDENTIALS` pointing at an external
account JSON (written by the CI step from the OIDC token) is the only file-based credential that appears, and
only inside CI.

## Roles matrix (summary of `docs/IAM_MATRIX.md`)

| Principal | Roles | Where |
|---|---|---|
| Attendee group (shared project, `setup_wif.sh --attendee-group`) | `roles/aiplatform.user`, `roles/bigquery.jobUser`, `roles/bigquery.user` (creates `cymbal_beauty_<namespace>_*`), `roles/serviceusage.serviceUsageConsumer`, `roles/pubsub.editor`, `roles/logging.viewer`, `roles/cloudtrace.user`, `roles/agentregistry.viewer`, `roles/discoveryengine.editor`; `roles/iam.serviceAccountUser` on `store-ops-dev-runtime@`; `objectAdmin` on the staging bucket | project |
| `store-ops-<env>-runtime@` | `roles/aiplatform.user`, `roles/bigquery.jobUser`, `roles/cloudtrace.agent`, `roles/logging.logWriter`, `roles/monitoring.metricWriter`, `roles/discoveryengine.viewer`; dataset `READER` on `cymbal_beauty_<namespace>_<env>`; `roles/bigquery.dataEditor` on `store_tasks` only; `roles/secretmanager.secretAccessor` per `store-ops-<env>-*` secret | per env |
| `cicd-evaluator@` | custom role `cymbalModelCaller` (`aiplatform.endpoints.predict` only), `roles/bigquery.jobUser`, dataset `READER` on `cymbal_beauty_<namespace>_dev` | dev only |
| `cicd-deployer-<env>@` | `roles/aiplatform.user`, `roles/serviceusage.serviceUsageConsumer`, `objectAdmin` on the staging bucket, `roles/iam.serviceAccountUser` on `store-ops-<env>-runtime@` | per env |
| Approver (human) | `roles/cloudbuild.approver` | Cloud Build triggers |
| Agent Engine service agent | `roles/iam.serviceAccountUser` on the runtime SAs; `roles/secretmanager.secretAccessor` on referenced secrets | per SA, per secret |

Negative tests in `tests/iam/` (run under impersonation): the runtime identity cannot write to `products`; the
evaluator cannot deploy; the dev deployer cannot read a prod secret.

## Impersonation patterns

```bash
# gcloud and bq
gcloud --impersonate-service-account=cicd-evaluator@$P.iam.gserviceaccount.com projects describe $P
CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT=cicd-evaluator@$P.iam.gserviceaccount.com bq ls $P:cymbal_beauty_${WORKSHOP_NAMESPACE}_dev
# ADC for Python
gcloud auth application-default login --impersonate-service-account cicd-evaluator@$P.iam.gserviceaccount.com
```

```python
from google.auth import default, impersonated_credentials
src, _ = default()
creds = impersonated_credentials.Credentials(source_credentials=src,
    target_principal=f"cicd-evaluator@{P}.iam.gserviceaccount.com",
    target_scopes=["https://www.googleapis.com/auth/cloud-platform"], lifetime=900)
```

The caller needs `roles/iam.serviceAccountTokenCreator` on the target SA.

## Workload Identity Federation, step by step

```bash
gcloud iam workload-identity-pools create github --location=global --display-name=github --project $P
gcloud iam workload-identity-pools providers create-oidc github-oidc --location=global \
  --workload-identity-pool=github --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_id=assertion.repository_id,attribute.ref=assertion.ref" \
  --attribute-condition="assertion.repository_id=='123456789'" --project $P
gcloud iam service-accounts add-iam-policy-binding cicd-deployer-dev@$P.iam.gserviceaccount.com \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/$NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$OWNER/$REPO"
```

Any other CI that issues OIDC tokens uses the same provider shape: its issuer URL, an attribute mapping for the
claims it emits, and a condition that pins exactly one repository or workspace.

In GitHub Actions: `permissions: id-token: write` and `google-github-actions/auth@v2` with
`workload_identity_provider: ${{ vars.WIF_PROVIDER }}` and `service_account: ${{ vars.WIF_SERVICE_ACCOUNT }}`.
In a generic step: write an external-account credential file
(`gcloud iam workload-identity-pools create-cred-config ... --credential-source-file=token.txt`) and export
`GOOGLE_APPLICATION_CREDENTIALS`.

## Quota project rules

- `gcloud auth application-default set-quota-project $P` after every ADC login.
- `GOOGLE_CLOUD_QUOTA_PROJECT=$P` overrides it for one shell.
- Symptoms of a wrong quota project: 403 with `serviceusage.services.use` or "API has not been used in project
  <some other project>".

## Attendee pre-flight in one line

```bash
uv sync --all-extras && uv run python scripts/namespace.py    # writes WORKSHOP_NAMESPACE into .env; then:
uv run python scripts/check_env.py --stage prereqs                    # tools, both sign-ins, namespace, project, APIs, location, model probe (PASS or a fix hint)
```
