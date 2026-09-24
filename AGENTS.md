# Cymbal Beauty ADK workshop

`AGENTS.md`, `CLAUDE.md` and `GEMINI.md` hold the same text, so every coding agent (Claude Code, Gemini CLI,
Antigravity, Cursor, Copilot) works from the same instructions; `tests/unit/test_agent_guides.py` keeps them
identical. Two nested guides add detail for their folders: `agents/cymbal_store_ops/AGENTS.md` (the agent tree) and
`deployment/AGENTS.md` (environment safety). Read the one for the folder you change.

## What this repository is

A three-hour hands-on workshop on Google ADK 2.x agents for a fictional beauty retailer, Cymbal Beauty. The running
example is the store operations agent in `agents/cymbal_store_ops/`: a coordinator that plans the store's day with a
parallel-read workflow, consults specialists for shelf availability, pickup coverage and loss, hands coaching
conversations to a coaching agent, and makes store task changes only after a person confirms them. It runs over a
synthetic dataset in BigQuery, with evaluations, deployment to Agent Runtime and a promotion pipeline.

The eight lab notebooks in `notebooks/` and the twelve quickstart walkthroughs are hand-written in the style of the
GoogleCloudPlatform/generative-ai samples: every code cell is a plain SDK call with a short explanation before it.
There is no notebook generator and no helper module. `docs/NOTEBOOK_AUTHORING.md` is the style guide and
`tests/unit/test_notebook_style.py` checks it.

## How the deployed agent reaches data

The deployed agent reads every store record through the MCP server in `services/store_mcp/` on Cloud Run. The 30
reads are listed once in `agents/cymbal_store_ops/mcp_catalog.py`; the server registers each from the agent's own
function and runs the agent's store and role checks itself. With `CYMBAL_MCP_URL` set, `make_root_agent` swaps
each agent's local reads for its own `McpToolset`, and the briefing readers, report delivery and the end-of-day
dashboard call the server from code (`call_mcp_read`). `deployment/deploy.py` refuses to deploy without the MCP
settings. Task writes (they need ADK's confirmation step), sign-in, memory and Vertex AI Search stay in the agent.
Run locally (notebooks, `adk web`), the agent reads BigQuery directly with your own credentials.

Model: `gemini-3.8-flash` on the global endpoint at MEDIUM thinking; the briefing's plan writer alone runs at LOW
(`plan_writer_thinking_level` in `config/envs/<env>.yaml`).

## Prerequisites

`uv`, `gcloud` (with `gcloud auth login` and `gcloud auth application-default login`), `bq`, Python 3.12. Copy
`.env.example` to `.env` and set `GOOGLE_CLOUD_PROJECT`, then `uv run python scripts/namespace.py`. Gemini 3.x is
served from the global endpoint (`GOOGLE_CLOUD_LOCATION=global`); a 404 from a regional location is a location
error, not a model error.

## Repository map

```text
agents/cymbal_store_ops/   agent.py (create_app, make_root_agent) · sub_agents/ · tools/ · callbacks.py · plugins.py · trace.py
                           · prompts/ · config/envs/ · governance/ (model_armor.py, cost.py) · mcp_catalog.py, mcp_connection.py,
                           mcp_auth.py (the MCP reads and the signed session scope) · events/ · reports/ (end-of-day PDF)
services/store_mcp/        the MCP server on Cloud Run
data/                      generate.py (deterministic) · schemas/ · load.sh · teardown.sh
eval/                      evaluation sets, custom metrics, run_broad.py (fifty questions), benchmark_writer.py, publish_vertex.py
journeys/                  multi-turn conversation tests (run.py)
tests/                     unit (no cloud) · integration (live) · eval (the CI gate) · iam · quickstarts
deployment/                release.py · deploy.py · mcp_deploy.py · mcp_probe.py · mcp_register.py · traffic.py · smoke.py · teardown.py
cloudbuild/                the release and promotion pipeline
frontend/                  the tablet app: server.py and static/ (ARCHITECTURE.md explains a turn end to end)
notebooks/                 the eight workshop labs
quickstarts/               twelve standalone examples, each with a README, a diagram and a walkthrough notebook
docs/                      guides, diagrams (Gemini renders, briefs in docs/diagrams/prompts/), patterns/, COMMANDS.md
skills/                    skills for coding agents working in this repository
scripts/                   check_env.py, namespace.py, resources.py, check_docs.py, quickstart_apps.py and other checks
```

## Working on a change

1. **Understand.** Read the notebook for the area you touch, `docs/ARCHITECTURE.md`, and the pattern page in
   `docs/patterns/` for the code you change.
2. **Build.** Change the code, then try it: `uv run adk web agents --port 8000`, or the tablet app with
   `uv run python frontend/server.py --target local --port 8080`.
3. **Evaluate.** After any prompt, tool or routing change, run the gate:
   `uv run pytest tests/eval -q -k test_golden_gate_passes`. `uv run python deployment/change_risk.py --base origin/main`
   is the review CI runs; read its verdict.
4. **Test.** `uv run pytest tests/unit tests/quickstarts -q` (no cloud) and `uv run pytest tests/integration -q -m live`
   before you call a change done. A notebook change is run top to bottom against your own namespace, saved with
   outputs cleared, and checked with `uv run pytest tests/unit/test_notebook_style.py -q`.
5. **Deploy to dev** only after the person asks:
   `uv run python deployment/release.py && uv run python deployment/deploy.py --env dev --release release.json`.
   Never deploy preprod or prod from a laptop; they go through the pipeline with approvals.
6. **Promote** through the Cloud Build approval triggers in `cloudbuild/`; see `docs/PROMOTION_STRATEGY.md`.

`docs/COMMANDS.md` lists the common commands.

## Conventions

- ADK 2.9 idioms: build agents with factory functions (an agent instance can have only one parent); sub-agent
  modes (`chat`, `task`, `single_turn`) decide hand-over or tool call; optional state templating `{key?}`; no broad
  `try/except` around agent code (the framework drives retries and confirmations).
- **No fallbacks.** A missing variable, credential, dataset or service fails loudly with a fix hint. Never add a
  "try X, else quietly do Y" path.
- Tools return the shared envelope `{"status": "SUCCESS", "rows": [...]}` or `{"status": "ERROR", "error_details": ...}`.
  Tool names and `output_key`s are contracts with the evaluations; change them together.
- A new store read goes into `mcp_catalog.READS` so the deployed agent serves it through MCP. A new write stays in
  the agent and asks for confirmation.
- `tools/store_query.py` offers allowlisted fields, filters and aggregates across nine resources; the model chooses
  the query and code enforces store and role scope. Report delivery shows up to 5,000 rows in the app and returns
  only metadata to the model; completeness reflects the full matching count.
- Scenario prompts are examples, not routing instructions. Prompts say what to do, never which tool answers which
  question; tools describe their own capabilities.
- Identity and store scope come from session state (`user:user_id`, `user:store_id`, `user:role`), never from tool
  arguments or chat text; `enforce_store_scope_before_tool` and `enforce_role_before_tool` enforce it.
- The retailer is **Cymbal Beauty** everywhere in code, data and prompts. Never introduce real retailer names.
- Optional platform controls are configuration and never silent: `MODEL_ARMOR_TEMPLATE` switches prompt screening on,
  `MEMORY_BANK_ENGINE` adds memory, `SOP_DATA_STORE` adds the procedures search; `deploy.py` prints which are on.
- Diagrams in `docs/diagrams/` are Gemini renders; regenerate them from their briefs in `docs/diagrams/prompts/`.
- Commands in docs and notebooks are the real commands. There is no Makefile.
- `ruff` clean; tests real (no mocks of the thing under test); commits in the imperative mood.
- **No AI attribution** in commit messages, PR descriptions or files.

## Safety rules

- Never print, log or commit secrets or `.env`; secrets reach the agent as Secret Manager references.
- BigQuery is read-only for agents except `store_tasks`, through reviewed manager creation and delegation and
  confirmed completion or blocker reports on the signed-in associate's own task (ownership check and idempotency).
- Do not change `MODEL` or `GOOGLE_CLOUD_LOCATION` unless asked; a 404 on the model is a location problem.
- Never run `deployment/deploy.py --env preprod|prod` or `deployment/traffic.py` locally.
- No deletes (`deployment/teardown.py`, `data/teardown.sh`, `scripts/resources.py --delete`, `bq rm`) without an
  explicit request.
- Do not commit `.adk/`, `data/out/`, `build/`, `release.json`, `deployment/deployment_info.*.json`, or installed
  skill copies.
- Stop and report after three identical errors instead of retrying.

## Skills

Install with `bash scripts/install_skills.sh --agent <antigravity|gemini-cli|claude|all>`, then use them by name.
If your agent does not list skills, read the file.

| Skill | Use when | File |
|---|---|---|
| google-adk | building or changing agents, tools, callbacks, evaluations, the `adk` CLI | `skills/google-adk/SKILL.md` |
| gemini-genai | calling Gemini directly with the google-genai SDK (judges, probes) | `skills/gemini-genai/SKILL.md` |
| agent-platform-runtime | deploying, updating, promoting or debugging on Agent Runtime; pipelines | `skills/agent-platform-runtime/SKILL.md` |
| gcp-integration | gcloud, bq, IAM, Workload Identity Federation, Secret Manager; 401 and 403 diagnosis | `skills/gcp-integration/SKILL.md` |
| gcloud-cli | running or writing a `gcloud` or `bq` command in your own namespace | `skills/gcloud-cli/SKILL.md` |
| bitbucket-integration | source or pipelines in Bitbucket, keyless sign-in to Google Cloud | `skills/bitbucket-integration/SKILL.md` |
| cymbal-beauty-domain | writing SQL, tests, evaluation cases or prompts against the workshop data | `skills/cymbal-beauty-domain/SKILL.md` |

## Read next

`SETUP.md` · `notebooks/README.md` · `docs/ARCHITECTURE.md` · `docs/patterns/README.md` · `frontend/ARCHITECTURE.md` ·
`docs/GOVERNANCE.md` · `docs/PROMOTION_STRATEGY.md` · `docs/COMMANDS.md`
