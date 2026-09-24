# Troubleshooting

Every check in `uv run python scripts/check_env.py --stage prereqs` and `uv run python scripts/check_env.py --stage ready` prints the command that fixes it. This table covers what those
checks cannot see. Symptom → diagnostic → fix.

| Symptom | Diagnostic | Fix |
|---|---|---|
| `Your Google sign-in has expired or is missing; nothing was run.` | application default credentials and the gcloud CLI sign-in expire separately, after some hours | run the `Fix:` line it prints (`gcloud auth application-default login`, and `gcloud auth login` when it names the CLI), then rerun the command; `uv run python scripts/check_env.py --stage prereqs` checks both |
| `404 … publishers/google/models/gemini-3.8-flash` | `grep GOOGLE_CLOUD_LOCATION .env` shows a region | Gemini 3.x is served from `global`; set `GOOGLE_CLOUD_LOCATION=global` (local tools) — the agent itself pins `global` on its client |
| `RuntimeError: GOOGLE_CLOUD_PROJECT is not set` | `.env` missing or not copied | `cp .env.example .env` and set the project |
| `bigquery backend failed its healthcheck: 403` | `bq query --use_legacy_sql=false "SELECT 1 FROM cymbal_beauty_${WORKSHOP_NAMESPACE}_dev.products LIMIT 1"` fails for that identity | `roles/bigquery.dataViewer` on your namespaced dataset plus `roles/bigquery.jobUser`; for engines run `deployment/iam/setup_wif.sh` |
| the agent does not load in `uv run adk web agents --port 8000` | the backend health check failed at startup (the error names the dataset or variable) | fix what it names; `uv run python scripts/check_env.py --stage ready` |
| `Correlated subqueries … not supported` | a domain tool used `ARRAY(SELECT …)` | join and aggregate (`get_product_details` shows the pattern) |
| the task already exists / the backroom check is already open | a task was created in an earlier run | `bash data/load.sh --env dev --tables store_tasks` (reloads `store_tasks`) |
| no confirmation dialog for the task | `store_tasks.require_confirmation: false` in `config/envs/<env>.yaml` | set it back to `true` |
| `no store is signed in for this session` | state not seeded | say "I'm U-M014, the store manager at Naperville" (demo sign-in) or use the frontend's "Sign in as store manager" |
| `blocked by policy: this session is scoped to store S-014` | a tool was asked about another store | sign in as the district manager (`A-1001`), the only role that crosses stores |
| eval custom metric `NOT_EVALUATED` | wrong function signature or import path | `(eval_metric, actual, expected, conversation_scenario)`; `code_config.name = eval.metrics.<fn>` |
| eval trajectory fails on some runs only | the model added an optional argument | the metric checks the golden's arguments as a subset; keep goldens to the arguments that matter |
| deploy: `failed to start and cannot serve traffic` | Logs Explorer for the engine shows `No module named 'agents'` | run `deploy.py` from the repo root; `extra_packages=["agents"]` |
| `uv run python quickstarts/02-rag-knowledge-agent/sop_data_store.py setup`: `… was deleted recently and Vertex AI Search is still removing it` | the data store was torn down in the last couple of hours and its name is not free yet | run `uv run python quickstarts/02-rag-knowledge-agent/sop_data_store.py setup` later, or `uv run python scripts/namespace.py --set <name>`, then `uv run python data/generate.py && bash data/load.sh --env dev` and `uv run python quickstarts/02-rag-knowledge-agent/sop_data_store.py setup` |
| `smoke.py` says the run ended without an answer; engine logs show `policy_lookup could not search the SOP data store … 403 Permission 'discoveryengine.servingConfigs.search' denied` | the runtime identity cannot search Vertex AI Search (the engine was deployed with `SOP_DATA_STORE` set) | `roles/discoveryengine.viewer` on `store-ops-<env>-runtime@`: rerun `deployment/iam/setup_wif.sh`, or deploy without `SOP_DATA_STORE`; IAM changes can take a minute or two |
| engine answers but tools error | Logs Explorer shows `TOOL ERROR … 403 Access Denied` | the runtime service account lacks dataset access (`setup_wif.sh`) |
| engine logs `Failed to export span batch code: 403` | tracing roles missing | `roles/cloudtrace.agent`, `roles/logging.logWriter`, `roles/monitoring.metricWriter` on the runtime SA |
| `traffic.py` refuses the split | percentages do not sum to 100, or a stale candidate | name the revision explicitly; rerun `release.py` on the intended commit |
| `bq add-iam-policy-binding` says "requires allowlisting" | dataset-level IAM bindings are not enabled in that project | dataset access entries via `bq update --source` (what `setup_wif.sh` does) |
| the MCP client lists no tools | the server crashed or printed to stdout | run `cymbal_mcp_server.py` alone and read stderr |
| Gemini Enterprise shows the agent but replies fail | the app cannot reach the engine, or the engine has no traffic | `uv run python deployment/register_gemini_enterprise.py register --env dev --app-id <app-id> … list`; `traffic.py list --env <env>` |
| `check_docs.py` fails on a link | the URL prefix is not in `docs/link_allowlist.txt` | add the official documentation prefix; never internal links |

Escalation: engine logs (`docs/OBSERVABILITY.md`), then the ADK troubleshooting pages at https://adk.dev/ and the
Agent Runtime deployment troubleshooting page linked from the deploy error.
