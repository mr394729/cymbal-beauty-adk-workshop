# Bitbucket Pipelines: the full template, variables and mapping

Written from Atlassian's documentation and from `.github/workflows/ci.yml`; **not run in a Bitbucket workspace**.
The Google Cloud commands inside it were run live on 2026-09-17. Create the file as `bitbucket-pipelines.yml` at
the root of your copy of the repository, and copy this skill's `scripts/wif_login.sh` to `ci/wif_login.sh`.

## Review before the first run

1. Open `.github/workflows/ci.yml` next to the YAML below: every `run:` line there has a `script` line here.
2. On the repository's OpenID Connect settings page, read the issuer, the audience and the repository UUID; they
   must equal the provider's values (recipe 1 in `SKILL.md`).
3. Predict what the first pull request will do: the lint step passes without any cloud access; the eval step
   prints `wif_login: signed in to <project> as cicd-evaluator@…` before anything else. If that line is missing,
   stop there: nothing after it can work.

## bitbucket-pipelines.yml

```yaml
image: python:3.12-slim

definitions:
  caches:
    uv: ~/.cache/uv
  scripts:
    - &install |
        pip install --quiet uv
        uv sync --locked --all-extras
    - &gcloud |
        apt-get update -qq && apt-get install -y -qq curl >/dev/null
        curl -sSL https://sdk.cloud.google.com | bash -s -- --disable-prompts --install-dir=/opt >/dev/null
        export PATH="/opt/google-cloud-sdk/bin:$PATH"
  steps:
    - step: &lint-test
        name: lint + tests (no cloud)
        caches: [uv]
        script:
          - *install
          - uv run ruff check .
          - uv run python scripts/check_skills.py
          - uv run python scripts/check_docs.py
          - uv run pytest tests/unit tests/quickstarts -q
    - step: &eval-gate
        name: eval gate (read-only evaluator identity)
        oidc: true
        max-time: 30
        caches: [uv]
        script:
          - *install
          - *gcloud
          - source ci/wif_login.sh
          - export GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_LOCATION=global STORE_OPS_ENV=dev EVAL_NUM_RUNS=2
          - uv run python scripts/check_env.py --stage prereqs
          - uv run python eval/build_eval_set.py
          - uv run pytest tests/eval -q -p no:cacheprovider
        artifacts:
          - agents/cymbal_store_ops/.adk/eval_history/**

pipelines:
  pull-requests:
    '**':
      - step: *lint-test
      - step:
          <<: *eval-gate
          condition:
            changesets:
              includePaths:
                - agents/**
                - eval/**
                - tests/**
                - pyproject.toml
                - uv.lock
  branches:
    main:
      - step: *lint-test
```

There is no deploy step, on purpose. A merge to `main` starts the Cloud Build ladder through the Cloud Build
connection to the Bitbucket repository; the approvals and the deployer identities live there
(`deployment/iam/setup_cloudbuild_triggers.sh`, `docs/PROMOTION_STRATEGY.md`).

The `curl | bash` line is Google's documented SDK bootstrap. It costs about a minute per run; an image that
already carries `gcloud` and Python 3.12 removes it.

## Repository variables

| Variable | Secured | Value |
|---|---|---|
| `GCP_PROJECT_ID` | no | the project id |
| `GCP_PROJECT_NUMBER` | no | the numeric project number (it is part of the provider's resource name) |
| `WIF_SERVICE_ACCOUNT` | no | `cicd-evaluator@<project>.iam.gserviceaccount.com` |
| `WORKSHOP_NAMESPACE` | no | the namespace whose `cymbal_beauty_<namespace>_dev` dataset the gate reads |

Nothing is secured because nothing is secret: the identity token is minted per step and exchanged for a
short-lived Google token. `wif_login.sh` also reads optional `WIF_POOL` (default `cicd`) and `WIF_PROVIDER`
(default `bitbucket-oidc`).

## Mapping

| Bitbucket Pipelines | GitHub Actions | Cloud Build |
|---|---|---|
| `bitbucket-pipelines.yml` | `.github/workflows/*.yml` | `cloudbuild/*.yaml` |
| `pipelines.pull-requests` | `on: pull_request` | pull-request trigger |
| `pipelines.branches.main` | `on: push: branches: [main]` | push trigger |
| step | job | step |
| `script` | `run` | `args` / `script` |
| `oidc: true` + `BITBUCKET_STEP_OIDC_TOKEN` + `wif_login.sh` | `permissions: id-token: write` + `google-github-actions/auth` | the trigger's own service account (`--service-account`) |
| repository variables | `vars.*` | substitutions |
| secured variables | `secrets.*` | Secret Manager `availableSecrets` |
| `condition.changesets.includePaths` | `paths` / `paths-ignore` | `includedFiles` / `ignoredFiles` |
| `definitions.caches` | `setup-uv` cache / `actions/cache` | Cloud Storage cache steps |
| `pipelines.custom` with variables | `workflow_dispatch` inputs | manual trigger with substitutions |
| `deployment: <env>` (permissions need Premium) | `environment: <env>` | `--require-approval` triggers |
| YAML anchors (`&name`, `*name`, `<<:`) | reusable workflows / composite actions | none |

## Minute budget

| Run | Steps | Approx. minutes |
|---|---|---|
| pull request touching docs only | lint + tests | 4 |
| pull request touching agents | lint + tests + eval gate (`EVAL_NUM_RUNS=2`, seven cases) | 10 to 20 |
| merge to main | lint + tests | 4 |

The eval gate's time is model latency: three to six minutes on a quiet project, ten to fifteen when the project is
busy. Keep it behind `includePaths`, cache uv, and rehearse deploys in Cloud Build, not here.

## When the eval step fails before it starts

| Message | Cause | Fix |
|---|---|---|
| `wif_login: this step has no identity token` | `oidc: true` missing (an anchor override dropped it) | put it back on the step |
| `wif_login: Google Cloud refused the step's token` | issuer, audience or the `repositoryUuid` condition do not match | compare the provider with the OpenID Connect settings page, braces included |
| `wif_login: the token was accepted but … cannot be impersonated` | the `principalSet` binding is missing or names another UUID | recipe 1, last command |
| `[FAIL] WORKSHOP_NAMESPACE set` from `check_env.py` | the repository variable is missing | add it; the gate never guesses a namespace |
| `Not found: Dataset …cymbal_beauty_<namespace>_dev` | that namespace was never loaded | `bash data/load.sh --env dev` once, from a signed-in machine |
