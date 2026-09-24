# Promotion: dev to preprod to prod with approvals, WIF and a release manifest

## Principles the repo enforces

1. **Reviewed release identity across environments.** Each deployment build runs `deployment/release.py`, which
   exports the lock (`uv export --frozen`) and records the selected commit and the digest of the requirements
   exported from the lock in `release.json`. Every environment deploys `extra_packages=["agents"]` from that
   checkout, the shape the Agent Runtime docs show. Matching earlier passing evidence is an approval procedure,
   not an automatically verified artifact chain.
2. **Config, not code, differs per environment.** `agents/cymbal_store_ops/config/envs/<env>.yaml` holds
   engine id, runtime SA, `min_instances`, `traffic` mode, `approvals_required`, dataset names, `job_labels`,
   `secret_env_vars` (secret **version numbers**). The project id comes from `GOOGLE_CLOUD_PROJECT`.
3. **Secrets are references.** Secret Manager values are never copied through CI; the engine reads them at
   start via `secret_env`. Rotating a secret = new version number in YAML = new revision.
4. **Evals are gates.** PR gate: `pytest tests/eval` on the local agent (evaluator identity, read-only).
   Preprod gate: `eval/remote_eval.py` against the new revision. Prod: smoke + direct revision probes.
5. **Canary and rollback are traffic edits.** New prod code = revision at 0 % under `traffic_split_manual`;
   `traffic.py promote --revision <candidate> --percent 10`, probe, `--percent 100`, `prune`. `rollback --to <previous>` moves 100 % back.
6. **Identity separation.** `cicd-evaluator@` (read-only), `cicd-deployer-<env>@` (one per env),
   `store-ops-<env>-runtime@` (engine identity), approver = a human with `roles/cloudbuild.approver`.
7. **Serialise per engine.** Run one traffic-changing build per engine at a time; this repository does not
   configure a shared promotion lock. Scripts find the engine by its labels (`app`, `ns`, `env`), never by a local
   file, so a fresh build checkout updates the namespace's engine; duplicates are refused.

## release.json

```json
{
  "git_sha": "221797bd…", "git_dirty": false,
  "requirements": "build/requirements.txt", "requirements_sha256": "…",
  "adk_version": "2.9.0", "aiplatform_version": "1.165.1",
  "prompt_version": "<sha256 of prompts/*.md>", "config_version": "<sha256 of config/envs/*.yaml>",
  "data_version": "2026.09.12-1",
  "model": {"dev": "gemini-3.8-flash", "preprod": "gemini-3.8-flash", "prod": "gemini-3.8-flash"},
  "secret_versions": {"dev": {}, "preprod": {}, "prod": {"PARTNER_API_KEY": "store-ops-prod-partner-api-key:3"}}
}
```

`deploy.py --env preprod|prod --release release.json` refuses a dirty checkout or one whose commit or lock differs from the manifest.

## Cloud Build (Google-native path, fully built)

- `cloudbuild/ci.yaml`: `python:3.12-slim` + uv, `uv sync --locked`, `ruff`, `pytest tests/unit`,
  `pytest tests/eval` as the evaluator SA.
- `cloudbuild/deploy.yaml` with substitutions `_NAMESPACE`, `_ENV`: write the manifest, `deploy.py --env $_ENV`,
  `smoke.py`, `remote_eval.py`. For prod the new revision starts at 0 % (manual traffic).
- `cloudbuild/promote.yaml` (`_REVISION`, `_PERCENT`): `smoke.py --revision`, then `traffic.py promote`;
  `cloudbuild/rollback.yaml` (`_REVISION`): `traffic.py rollback --to`.
- Triggers created by `deployment/iam/setup_cloudbuild_triggers.sh PROJECT OWNER REPO NAMESPACE`, all named
  `<namespace>-…`: `ci` (PR), `deploy-dev` (push to main), and with `--require-approval` `deploy-preprod`,
  `prod-canary`, `prod-promote-10`, `prod-promote-100`, `prod-rollback`. Run one with
  `gcloud builds triggers run <namespace>-prod-promote-10 --region us-central1 --branch main --substitutions _REVISION=<rev>`;
  it waits until someone with `roles/cloudbuild.approver` runs
  `gcloud alpha builds approve BUILD_ID --location us-central1` (or clicks Approve in the console).
- Each trigger runs as its env's deployer SA (`--service-account`). Each deployer can act as its environment's
  runtime account; its project-wide Vertex AI permissions do not demonstrate complete isolation from other
  environments' engines.

## GitHub Actions (PR checks only)

`.github/workflows/ci.yml`: `pull_request` (never `pull_request_target`), `concurrency: ci-${{ github.ref }}`,
`paths-ignore: docs/**, slides/**`; jobs `lint-test` (uv cache, ruff, unit) and `eval-gate`
(`permissions: id-token: write`, `google-github-actions/auth@v2` with the WIF provider, `pytest tests/eval`).
Required reviewers on a private repo need GitHub Enterprise, so the Actions deploy ladder
(`deploy.yml`, `rollback.yml`) is reference material; its `assert-gate` step exits 1 when the environment has
no `required_reviewers` rule instead of silently deploying.

## Workload Identity Federation (keyless CI)

`deployment/iam/setup_wif.sh PROJECT OWNER REPO --namespace NS` creates pool `cicd` and the `github-oidc` provider:

| Provider | Issuer | Attribute condition (idea) |
|---|---|---|
| `github-oidc` | `https://token.actions.githubusercontent.com` | the repository name, or its numeric `repository_id` when known (names can be reclaimed); owner, ref and workflow claims are mapped but are not additional conditions in this script |

The bootstrap binds `roles/iam.workloadIdentityUser` on `cicd-evaluator@` (PR checks, read-only) to
`principalSet://.../attribute.repository/OWNER/REPO`. Use the variable names the script prints: `GCP_PROJECT_ID`,
`WORKSHOP_NAMESPACE`, `GCP_REGION`, `WIF_PROVIDER`, `WIF_EVALUATOR_SA` and `WIF_DEPLOYER_DEV_SA`; the dev-deployer
variable does not itself grant impersonation. Verify a provider with a read-only step first
(`gcloud auth print-identity-token`, `bq ls`).

## Live runbook (prod, 25 minutes, everything pre-created)

1. Show `release.json` and `traffic.py list` (100 / 0).
2. Approve the canary stage; `smoke.py --revision <new>` passes.
3. `traffic.py promote --percent 10`; show the split in the console and probe the new revision directly.
4. `traffic.py rollback --to <previous>` ("a traffic edit, not a build"), then approve 100 % or leave rolled back.
5. Old and new revision names stay on screen; `prune` runs after the session.

## Per-environment table

| | dev | preprod | prod |
|---|---|---|---|
| Engine / SA / dataset | own | own | own |
| Model | `gemini-3.8-flash` | candidate pin | pinned |
| Secrets | test values | test values | real, versioned |
| `min_instances` | 0 | 0 | 1 |
| `traffic` | `latest` | `latest` | `manual` |
| Approvals | 0 | 1 | 3 (canary revision, 10 %, 100 %); rollback is gated too |
| Deployed by | `uv run python deployment/release.py && uv run python deployment/deploy.py --env dev --release release.json` (human) | pipeline only | pipeline only |
