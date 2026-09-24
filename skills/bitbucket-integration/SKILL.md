---
name: bitbucket-integration
description: Running this repository's checks from Bitbucket Cloud Pipelines and reaching Google Cloud from them without a stored key (bitbucket-pipelines.yml for pull-request checks, oidc true and BITBUCKET_STEP_OIDC_TOKEN exchanged for short-lived Google credentials through Workload Identity Federation, the provider and its attribute condition, repository variables, caches and start conditions, handing promotion to the Cloud Build approval ladder, and the Bitbucket REST calls a coding agent needs for pull requests and pipeline results). Use when your source or pipelines live in Bitbucket, when writing or reviewing bitbucket-pipelines.yml, when a pipeline step gets 401 or 403 from Google Cloud, or when mapping a GitHub Actions workflow to Bitbucket. The Google Cloud half was run live; the Bitbucket half follows Atlassian's documentation and has not been run in a Bitbucket workspace, so prove the identity step first.
metadata:
  workshop: cymbal-beauty-adk-workshop
  version: "2.0"
  verified: "2026-09-17"
allowed-tools: Bash Read
---

# Bitbucket Pipelines with this repository

Nothing in the repository changes when the source lives in Bitbucket. The pipeline runs the same commands as
`.github/workflows/ci.yml`, gets Google credentials the same keyless way (an identity token per step, exchanged
through Workload Identity Federation), and hands promotion to the same Cloud Build approval ladder. This repo ships
no `bitbucket-pipelines.yml`: the template lives in this skill, so you create the file in your own copy.

**What was checked, and how.** On the verified date the Google Cloud side was run against a live project: the
federation pool, the `create-oidc` flags, the credential file that `create-cred-config` writes, and the commands
the steps run. The Bitbucket side (YAML keys, the OIDC claims, the REST calls) is written from Atlassian's
documentation and was **not** run in a Bitbucket workspace. Treat the first pipeline run as the test: the
`wif_login.sh` step proves the identity before anything else happens, and fails in words when it cannot.

## When to use

- Creating or reviewing `bitbucket-pipelines.yml` for a copy of this repo.
- Setting up the `bitbucket-oidc` federation provider, or debugging a 401/403 from a pipeline step.
- Translating `.github/workflows/ci.yml` (or another Actions workflow) into Pipelines.
- Opening a pull request, or reading a pipeline result, from a coding agent through the REST API.
- Deciding what runs in Bitbucket (fast checks) and what runs in Cloud Build (deploys behind approvals).

## Facts that override older docs

- **Keyless or nothing.** Set `oidc: true` on a step; Bitbucket puts a signed identity token in
  `BITBUCKET_STEP_OIDC_TOKEN`. No service-account key is ever stored as a repository variable. If the exchange
  fails, the step fails: there is no key to fall back to, by design.
- The issuer URL and the audience are shown on the repository's **OpenID Connect** settings page (Repository
  settings > Pipelines > OpenID Connect). The issuer has the shape
  `https://api.bitbucket.org/2.0/workspaces/<workspace>/pipelines-config/identity/oidc` and the audience
  `ari:cloud:bitbucket::workspace/<workspace uuid, no braces>`. The same page shows an example payload with the
  claims you can condition on; Atlassian's published example carries `repositoryUuid`, `workspaceUuid`,
  `branchName`, `pipelineUuid`, `stepUuid` and `deploymentEnvironment`.
- Build the attribute condition on `repositoryUuid` (it survives a rename). UUIDs in the claims **include the
  braces**: `{1a2b…}`. Copy them from the settings page; do not retype them. Never condition on the subject:
  `sub` is `{repository}:{environment}:{step}`, so it is different on every step.
- A step can ask for its own audience (`oidc: audiences: [...]`, at most ten, 150 characters each). The recipe
  below keeps Bitbucket's default audience and allows exactly that one on the provider.
- This repo's federation pool is `cicd` (created by `deployment/iam/setup_wif.sh` with the `github-oidc` provider).
  A Bitbucket provider is a second provider in the same pool; the service accounts and their roles do not change.
- Pull-request checks use the **read-only evaluator** identity `cicd-evaluator@`. A pipeline that can only read
  cannot deploy, whatever its YAML says. Deploy identities (`cicd-deployer-<env>@`) stay bound to Cloud Build.
- Promotion belongs in Cloud Build, not in the pipeline: Cloud Build connects to Bitbucket Cloud and Bitbucket
  Data Center repositories as a trigger source, its `--require-approval` triggers are the gates, and the
  per-environment deployer identities and the audit trail stay in Google Cloud. Bitbucket's own deployment
  permissions are a Premium-plan feature; do not design a gate that depends on the plan.
- The eval gate makes real model calls: it needs `GOOGLE_CLOUD_PROJECT`, `GOOGLE_GENAI_USE_VERTEXAI=TRUE`,
  `GOOGLE_CLOUD_LOCATION=global`, `STORE_OPS_ENV=dev` and a `WORKSHOP_NAMESPACE` whose dataset is loaded. It takes
  three to six minutes on a quiet project and ten to fifteen in a busy one; run it only when agent, eval or
  dependency files change.
- Pipelines syntax against Actions: step = job, `script` = `run`, repository variables = `vars`, secured
  variables = `secrets`, `oidc: true` = `permissions: id-token: write`, `condition.changesets.includePaths` =
  `paths`, `pipelines.custom` = `workflow_dispatch`. There is no `uses:`; reuse is YAML anchors.

## Repo map

| Path | Purpose |
|---|---|
| `references/pipelines-template.md` (this skill) | the full `bitbucket-pipelines.yml`, the variables table and the Actions mapping |
| `scripts/wif_login.sh` (this skill) | exchanges the step's token for Google credentials and proves the identity; copy it to `ci/wif_login.sh` in your repo |
| `.github/workflows/ci.yml` | the GitHub twin: the commands and environment the Bitbucket steps must match |
| `deployment/iam/setup_wif.sh` | creates the `cicd` pool, the service accounts and their roles; add the Bitbucket provider next to `github-oidc` |
| `deployment/iam/setup_cloudbuild_triggers.sh`, `cloudbuild/*.yaml` | the approval ladder that a merge to `main` starts |
| `docs/PROMOTION_STRATEGY.md`, `docs/IAM_MATRIX.md` | why promotion sits in Cloud Build; which identity may do what |

## Recipes

### 1. Create the federation provider (Google Cloud side, verified)

Review the two values on the OpenID Connect settings page first, then:

```bash
P=your-project-id; NUM=$(gcloud projects describe "$P" --format="value(projectNumber)")
ISSUER="https://api.bitbucket.org/2.0/workspaces/<workspace>/pipelines-config/identity/oidc"
AUDIENCE="ari:cloud:bitbucket::workspace/<workspace-uuid-without-braces>"      # copy it from the settings page
REPO_UUID='{<repository-uuid>}'                                                # braces included

gcloud iam workload-identity-pools describe cicd --project "$P" --location global --format="value(state)"   # ACTIVE
gcloud iam workload-identity-pools providers create-oidc bitbucket-oidc --project "$P" --location global \
  --workload-identity-pool cicd --issuer-uri "$ISSUER" --allowed-audiences "$AUDIENCE" \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository_uuid=assertion.repositoryUuid,attribute.branch=assertion.branchName" \
  --attribute-condition "assertion.repositoryUuid=='$REPO_UUID'"

gcloud iam service-accounts add-iam-policy-binding "cicd-evaluator@$P.iam.gserviceaccount.com" --project "$P" \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/$NUM/locations/global/workloadIdentityPools/cicd/attribute.repository_uuid/$REPO_UUID"
```

Check: `gcloud iam workload-identity-pools providers list --project "$P" --location global
--workload-identity-pool cicd --format="value(name.basename(),oidc.issuerUri,attributeCondition)"` prints
`github-oidc` and `bitbucket-oidc`, each with its condition. A provider without a condition accepts any
repository in the workspace: never leave it empty.

### 2. Exchange the token inside a step

`scripts/wif_login.sh` in this skill does it; the core is three commands:

```bash
printf '%s' "$BITBUCKET_STEP_OIDC_TOKEN" > "$TOKEN_FILE"
gcloud iam workload-identity-pools create-cred-config \
  "projects/$GCP_PROJECT_NUMBER/locations/global/workloadIdentityPools/cicd/providers/bitbucket-oidc" \
  --service-account "$WIF_SERVICE_ACCOUNT" --credential-source-file "$TOKEN_FILE" --output-file "$CRED_FILE"
export GOOGLE_APPLICATION_CREDENTIALS="$CRED_FILE"     # Python clients and ADK read this
gcloud auth login --cred-file "$CRED_FILE" --quiet      # gcloud and bq read this
```

The credential file holds no secret: it says where the token file is and which provider to present it to
(`"type": "external_account"`). Exchange at the start of the step; the token is short-lived and is not passed to
later steps.

### 3. The pull-request pipeline

The full file is in `references/pipelines-template.md`. Its shape:

```yaml
pipelines:
  pull-requests:
    '**':
      - step: *lint-test            # ruff, check_skills, check_docs, unit + quickstart tests; no cloud
      - step:
          <<: *eval-gate            # oidc: true, wif_login.sh, check_env, build_eval_set, pytest tests/eval
          condition:
            changesets:
              includePaths: ["agents/**", "eval/**", "tests/**", "pyproject.toml", "uv.lock"]
```

Review before the first run: the steps list must match `.github/workflows/ci.yml` line for line; if `ci.yml`
gained a check since this skill was verified, add it here too.

### 4. Promotion: let the merge start Cloud Build

Connect the Bitbucket repository to Cloud Build (console: Cloud Build > Repositories, 2nd gen, a host connection
for Bitbucket Cloud or Bitbucket Data Center; the steps are in the last reference below), then run `deployment/iam/setup_cloudbuild_triggers.sh` against that
connection. The ladder (`deploy-dev`, `deploy-preprod`, `prod-canary`, `prod-promote-10`, `prod-promote-100`,
`prod-rollback`) and its approvals are unchanged. The script was run with a GitHub connection only; with a
Bitbucket connection check the repository resource name it prints before you create the triggers.

### 5. Pull requests and pipeline results from an agent (REST)

Use a **repository access token** with the narrowest scopes (pull requests: write, pipelines: read), kept in the
environment as `BITBUCKET_TOKEN`; never in a file in the repo.

```bash
API="https://api.bitbucket.org/2.0/repositories/$BB_WORKSPACE/$BB_REPO"
# open a pull request from the current branch
curl -sf -X POST "$API/pullrequests" -H "Authorization: Bearer $BITBUCKET_TOKEN" -H "Content-Type: application/json" \
  -d "$(jq -n --arg t "$TITLE" --arg b "$(git branch --show-current)" \
        '{title:$t, source:{branch:{name:$b}}, destination:{branch:{name:"main"}}, close_source_branch:true}')" \
  | jq -r '.links.html.href'
# latest pipeline runs and their result
curl -sf "$API/pipelines/?sort=-created_on&pagelen=5" -H "Authorization: Bearer $BITBUCKET_TOKEN" \
  | jq -r '.values[] | [.build_number, .state.name, (.state.result.name // "-"), .target.ref_name] | @tsv'
```

`curl -f` makes an HTTP error a non-zero exit, so a wrong token fails the command instead of printing JSON you
then parse as success. Show the pull request title and target to the user before you create it.

## Gotchas

- `oidc: true` is per step. A step without it has no `BITBUCKET_STEP_OIDC_TOKEN`, and `wif_login.sh` says so.
- 403 `The caller does not have permission` right after the exchange usually means the `principalSet` binding
  names a different UUID (or lost its braces) than the token carries; compare with the settings page.
- An error from the token exchange that mentions the audience means the provider's `--allowed-audiences` is not the
  audience on the settings page (or the step declares its own `audiences`).
- `python:3.12-slim` has no `gcloud`. Install the SDK in the step (slow) or use an image that has both; the
  template shows the install.
- The built-in `pip` cache does not cover `uv`: define a custom cache for `~/.cache/uv`.
- Deployment environments must exist in repository settings before `deployment: <name>` is valid YAML to run.
- Build minutes are metered per plan: keep the eval gate on `includePaths`, and do not rehearse deploys here.
- A fork must not get cloud credentials. A fork is a different repository with a different `repositoryUuid`, so
  the provider's condition rejects its token: that condition, not a variable, is the control. Keep it.

## References

- [references/pipelines-template.md](references/pipelines-template.md), the full YAML, variables, Actions mapping, minute budget
- Configure bitbucket-pipelines.yml: https://support.atlassian.com/bitbucket-cloud/docs/configure-bitbucket-pipelinesyml/
- OIDC with resource servers: https://support.atlassian.com/bitbucket-cloud/docs/integrate-pipelines-with-resource-servers-using-oidc/
- The example token payload (on the AWS page; the claims are the same for any cloud): https://support.atlassian.com/bitbucket-cloud/docs/deploy-on-aws-using-bitbucket-pipelines-openid-connect/
- Variables and secrets: https://support.atlassian.com/bitbucket-cloud/docs/variables-and-secrets/
- Caches: https://support.atlassian.com/bitbucket-cloud/docs/cache-dependencies/
- Start conditions: https://support.atlassian.com/bitbucket-cloud/docs/pipeline-start-conditions/
- Deployments: https://support.atlassian.com/bitbucket-cloud/docs/set-up-and-monitor-bitbucket-deployments/
- Repository access tokens: https://support.atlassian.com/bitbucket-cloud/docs/repository-access-tokens/
- REST API: https://developer.atlassian.com/cloud/bitbucket/rest/intro/
- Federation with deployment pipelines: https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines
- Cloud Build with Bitbucket Cloud: https://docs.cloud.google.com/build/docs/automating-builds/bitbucket/connect-repo-bitbucket-cloud
