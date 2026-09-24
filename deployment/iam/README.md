# Deployment identities and triggers

`setup_wif.sh` configures identities and federation. Follow [cloud setup](../../SETUP.md),
[the IAM matrix](../../docs/IAM_MATRIX.md) and [pipeline documentation](../../cloudbuild/README.md).

`setup_cloudbuild_triggers.sh` produces an offline plan by default. It does not install the GitHub app,
start a build, or approve a promotion. A regional Cloud Build GitHub connection must finish account
authorization before the script can link the repository. The connection's `installationState.actionUri`
is the account authorization URL; `installationState.stage` must be `COMPLETE`.

```bash
bash deployment/iam/setup_cloudbuild_triggers.sh PROJECT OWNER REPOSITORY NAMESPACE \
  --connection github --eval-namespace EVALUATION_NAMESPACE \
  --runtime-settings /path/to/runtime.env --scope ladder --out build/cloudbuild-setup
```

Review `plan.json` and the trigger definitions. Repeat with `--apply` to link the repository and configure
disabled triggers. Add `--enable` only when the source revision and deployment configuration are ready.
`--verify` reads the actual configuration and records differences without changing it. None of these
options starts a build. Applying a plan without `--enable` disables the planned triggers.

| Scope | Triggers |
|---|---|
| `dev` (default) | Pull request CI; dev deploy on a push to `main` |
| `ladder` | Dev triggers plus manual preprod deploy, prod canary, two promotion stages and rollback |

Every manual promotion/deployment trigger requires human approval. They do not run automatically on
push. Each trigger uses its designated evaluator or environment deployer identity. Existing repository
resources must point to the exact requested GitHub repository.

The evaluation namespace should have its own prepared fixture dataset and evaluator read access.
Trigger setup never resets data. CI uploads evidence under the staging bucket's `ci/` prefix; the
evaluator needs bucket metadata access and object creation only in that prefix.

The runtime settings file contains plain `KEY=value` or `export KEY=value` assignments. Accepted agent
settings are `SOP_DATA_STORE`, `MEMORY_BANK_ENGINE`, `CYMBAL_MCP_URL`, `CYMBAL_MCP_AUDIENCE`,
`CYMBAL_MCP_CALLER_SERVICE_ACCOUNT`, `CYMBAL_MCP_SCOPE_SECRET` and `MODEL_ARMOR_TEMPLATE`.
MCP requires all four settings together. Its secret reference must use a numeric version such as
`scope-secret:1`; secret values and shell commands are rejected. These settings become dev trigger
substitutions. Existing optional-service substitutions survive updates that omit them; use an explicit
empty assignment to disable a feature. Preprod and prod need their own environment-specific settings.

`cloudbuild_runtime.py` records the resulting nonsecret configuration and browser installation script
in the build evidence. Review that evidence alongside the source and deployed revision.

### Private repository history for change-risk review

The CI archive path verifies the embedded source manifest and exact baseline diff.
Repository triggers use `prepare_risk_base.py` instead: it obtains a short-lived
Cloud Build repository read token, validates that the checkout origin matches the
configured repository, and passes the token through a temporary askpass process.
No token is put in Git configuration, command arguments or logs. CI installs Git
explicitly in its slim image.

After OAuth completes, `--apply` verifies that the dedicated workshop connection
contains only the expected workshop repository (an initially empty connection is
accepted before linking). It then grants `roles/cloudbuild.readTokenAccessor` to
`cicd-evaluator` **on that connection**, and reads the policy back. This is
connection-scoped permission, not repository-scoped permission. The connection
must remain dedicated to this repository; setup fails if any other repository is
linked. There is no project-wide grant or conditional-IAM assumption.

The authenticated private fetch still needs a live check after OAuth; local Git
tests do not establish repository authorization. While OAuth is pending, setup
stops before linking, granting IAM or creating triggers. Automatic repository
trigger validation is not yet complete.

PR review compares the merge-base with the target branch. Push review compares the
explicit `_PREVIOUS_SHA`, or the built commit's first parent when none is supplied;
it rejects a baseline equal to HEAD. To review every commit of a multi-commit push,
supply the actual previous pushed SHA. Missing ancestry fails closed; there is no
fallback to an empty diff. Fetch is bounded to 200 commits.

References: [Cloud Build history and private fetch](https://docs.cloud.google.com/build/docs/automating-builds/create-manage-triggers#including_the_repository_history_in_a_build),
[repository read-token API](https://docs.cloud.google.com/build/docs/api/reference/rest/v2/projects.locations.connections.repositories/accessReadToken).

For the prepared workshop, after completing the existing OAuth link:

```bash
uv run python deployment/iam/cloudbuild_setup.py \
  --project $GOOGLE_CLOUD_PROJECT --region us-central1 --connection github \
  --owner mr394729 --repository cymbal-beauty-adk-workshop \
  --namespace demo --eval-namespace demoq0921 --scope dev \
  --runtime-settings build/release-integrated-20260922/runtime.env \
  --out build/cloudbuild-setup-after-oauth --apply
```

That repeatable command links the sole expected repository, grants and verifies
read-token access on its dedicated connection, and configures disabled triggers.
Once the tested source is published, repeat with `--enable` to enable them.
Neither command starts a build. Preprod/prod approval triggers remain a separate
`--scope ladder` operation with human approval retained.
