# Developer skills

Seven skills that make a coding agent (Gemini CLI, Claude Code) productive in this
repo and on Google Cloud. They are for **developers' agents**, not for the ADK agents in `agents/`.
Each skill is a folder with a `SKILL.md` (the map: when to use it, facts that override older docs, repo
map, recipes, gotchas) and `references/` (the detail), following the open Agent Skills format
(https://agentskills.io/specification).

| Skill | One-line trigger |
|---|---|
| `google-adk` | agents, tools, callbacks, modes, state, evals, the `adk` CLI |
| `gemini-genai` | direct Gemini calls with google-genai on Vertex (global endpoint, gemini-3.8-flash) |
| `agent-platform-runtime` | deploy/update/promote on Agent Runtime; revisions and traffic; pipelines |
| `gcp-integration` | `gcloud`, `bq`, ADC, IAM, WIF, Secret Manager, 401/403 self-diagnosis |
| `gcloud-cli` | driving `gcloud` and `bq` safely from an agent: read before change, `--project`/`--region` always, `--format` not tables, only your namespace |
| `bitbucket-integration` | Bitbucket Pipelines for this repo: PR checks, keyless sign-in through WIF, promotion handed to Cloud Build, pull requests over REST |
| `cymbal-beauty-domain` | the synthetic dataset: schema, fixtures, golden prompts, SQL |

## Install

```bash
bash scripts/install_skills.sh --agent gemini-cli       # → .agents/skills/
bash scripts/install_skills.sh --agent claude           # → .claude/skills/   (symlinks)
bash scripts/install_skills.sh --agent all
```

Then ask your agent "Which skills do you have?" — expected: the seven names above.

## Golden activation prompts

| Skill | Try |
|---|---|
| google-adk | "Add a `get_planogram_status` tool to inventory_excellence that reuses DataBackend" · "Why does inventory_excellence show as a tool call and not a transfer?" · "Why is daily_briefing an AgentTool and not a task-mode sub-agent?" |
| gemini-genai | "Classify 100 reviews into sentiment JSON with gemini-3.8-flash" · "Why do I get 404 for gemini-3.8-flash in us-central1?" · "Generate 20 synthetic guest feedback rows with structured output" |
| agent-platform-runtime | "Deploy the store operations app to dev and run the smoke test" · "Show prod revisions and shift 10 % to the newest" · "Add a Secret Manager-backed PARTNER_API_KEY to preprod" |
| gcloud-cli | "List every resource in the project that carries my namespace" · "How many bytes would this query scan? Do not run it" · "Get the URL of my Cloud Run service into a variable" · "Approve the waiting Cloud Build" |
| bitbucket-integration | "Write bitbucket-pipelines.yml with the same checks as ci.yml" · "My pipeline step gets 403 from BigQuery — why?" · "Open a pull request for this branch in Bitbucket" |
| gcp-integration | "bq says Access Denied on my cymbal_beauty_<namespace>_dev dataset — why?" · "Create the runtime service accounts with least privilege" · "Which identity is my ADC using?" |
| cymbal-beauty-domain | "List the on-shelf exceptions at S-014 with their BOPIS demand" · "Add a unit test that Priya (A-1004) is free with the BOPIS skill at 09:00" · "What columns does store_inventory have and how do I join stores?" |

## Lint

`uv run python scripts/check_skills.py` — frontmatter, sizes, referenced files, forbidden strings, URL allowlist,
AGENTS.md table ⇔ folders, generated schema freshness. Runs in `uv run ruff check . && uv run python scripts/check_skills.py && uv run python scripts/check_docs.py` and CI.
