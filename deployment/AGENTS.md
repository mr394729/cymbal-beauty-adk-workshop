# Coding agent guide — deployment

| Script | Purpose |
|---|---|
| `release.py` | export the lock, write `release.json` (git sha, lock digest, prompt/config/data versions, model and secret versions) |
| `deploy.py --env dev|preprod|prod --release release.json [--dry-run]` | create/update the Agent Runtime engine for an environment (docs-shaped config: `extra_packages=["agents"]`, `requirements`, `env_vars`, `service_account`) |
| `smoke.py --env … [--revision]` | one real query against the deployed engine; exit 1 on failure |
| `traffic.py list|promote|rollback|prune --env prod` | revision traffic management (prod runs a manual split) |
| `remote_eval.py` | golden prompts against a deployed revision |
| `register_gemini_enterprise.py` | register/update/list/delete the agent in a Gemini Enterprise app |
| `teardown.py --env … --yes` | delete the engine and its revisions |
| `iam/setup_wif.sh` | service accounts, least-privilege roles, Workload Identity Federation providers |

Rules: always `--dry-run` first; deploy **dev only** from a laptop and only when asked; preprod/prod deploy
through the pipeline with approvals; `traffic.py` refuses splits that do not sum to 100; the engine is resolved by namespace/environment labels and the deploy result is saved in an ignored local record;
secrets are Secret Manager references in `secret_env_vars`, never values. Pre-flight: `uv run python scripts/check_env.py --stage prereqs` and
`skills/gcp-integration/scripts/check_adc.sh`. Skills: agent-platform-runtime, gcp-integration.
