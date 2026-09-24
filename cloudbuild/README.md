# Build, deploy and promote

[Workshop home](../README.md) · [Notebook 05](../notebooks/05_deploy_and_promote.ipynb) · [Deployment scripts](../deployment/README.md)

These are Cloud Build pipeline definitions. Notebook 05 follows one change through them, from pull request to
production; running the same commands on a laptop gives no identities, approvals or deployment evidence.

![Application and agent release lifecycle](../docs/diagrams/agent-lifecycle.png)

| Pipeline | Steps and purpose |
|---|---|
| [ci.yaml](ci.yaml) | Install locked dependencies, lint, run unit tests, review the change for risk (`deployment/change_risk.py`: path floors plus a model reading the diff; high fails the check), run the live evaluation gate |
| [deploy.yaml](deploy.yaml) | Build release manifest, deploy a revision, smoke and evaluate that revision, save evidence |
| [promote.yaml](promote.yaml) | Smoke the selected revision and change its traffic percentage |
| [rollback.yaml](rollback.yaml) | Return traffic to a selected earlier revision |
| [frontend.yaml](frontend.yaml) | Build and deploy the tablet service |

The deploy pipeline runs its evaluation after deployment; it is not an optional step in this configuration.
Approval requirements come from triggers created by
[setup_cloudbuild_triggers.sh](../deployment/iam/setup_cloudbuild_triggers.sh), not from a local command or an arrow
in the diagram. Connect the source repository and configure identities and triggers before demonstrating it live.

Promoting a revision and deploying an environment are separate actions. Keep evaluation evidence tied to the
source, model configuration, dataset and revision under review. See [promotion strategy](../docs/PROMOTION_STRATEGY.md).

CI uses `_EVAL_NAMESPACE` when supplied, otherwise `_NAMESPACE`. Its live local-agent gate explicitly
excludes optional RAG, MCP, memory and Model Armor services; the deployed-revision checks exercise the
release's configured services. CI installs Chromium and runs the actual PDF rendering checks alongside
unit tests. Both unit and evaluation JUnit results are retained under `ci/$BUILD_ID/`.

Deployment services are explicit trigger substitutions. The four `_CYMBAL_MCP_*` connection settings are required:
the deployed agent reads store data only through its MCP server, and `deploy.py` refuses to deploy without them.
`_SOP_DATA_STORE`, `_MEMORY_BANK_ENGINE` and `_MODEL_ARMOR_TEMPLATE` are optional.
The signing secret is a pinned Secret Manager reference. The release records these nonsecret settings
in `build/runtime-features.json`; the deployment archive includes the report browser installation script.
See [trigger setup](../deployment/iam/README.md) for offline planning, disabled configuration and enabling.

Remote checks use the shared streaming decoder against the selected revision. They accept alternative
successful operational reads while retaining identity, factual-answer and approval assertions. A single
remote approval probe pauses for confirmation and must not complete a write.

CI writes allowlisted evidence to the private `ci/<build-id>/` bucket prefix in
exit cleanup, before a failed test or promotion-risk gate can prevent normal
artifact upload. `evidence-eval.tar.gz` contains the evaluation XML, unit XML,
recorded ADK result JSON and metrics CSV under `build/eval_runs`, plus available
risk reports. The risk step independently saves `evidence-risk.tar.gz` so its
reports survive even if evaluation fails first. Each bundle records source-file
hashes and the original step exit status.

The uploader rejects symlinks, unrelated build files and paths outside the
workspace, and caps files and bytes. It never includes browser cookies, runtime
environment files or arbitrary `build/` contents. Upload failure is logged and
preserves the original test status; it cannot turn a failed test into a pass.

This applies to future builds. Build `9df1f70d-82bb-4a63-aeb3-681582c5112e`
passed its functional checks but failed its HIGH promotion-risk gate before the
standard artifact upload. Its captured successful answers and writer timings
are unavailable; this change does not reconstruct that missing evidence.
