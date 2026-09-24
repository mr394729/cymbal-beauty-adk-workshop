# Common commands

[Workshop home](../README.md) · [Setup](../SETUP.md) · [Notebook labs](../notebooks/README.md)

Run these from the repository root. Python commands read `GOOGLE_CLOUD_PROJECT` and `WORKSHOP_NAMESPACE` from
`.env`; the shell scripts read `.env` too, and a value set on the command line wins. `<env>` is `dev` unless you
work in preprod or prod through the pipeline.

## Set up

| Command | What it does |
|---|---|
| `uv sync --all-extras` | Install the Python environment |
| `uv run python scripts/namespace.py [--set <name>]` | Show your namespace, or set it in `.env` |
| `uv run python scripts/check_env.py --stage prereqs` | Check tools, sign-in, project, APIs, location and the model |
| `uv run python scripts/check_env.py --stage ready` | Check your dataset, row counts and named records |
| `uv run python -m agents.cymbal_store_ops.preflight` | Check that both Google Cloud sign-ins are current |

## Data

| Command | What it does |
|---|---|
| `uv run python data/generate.py && bash data/load.sh --env dev` | Generate the dataset and load it into `cymbal_beauty_<namespace>_dev` |
| `bash data/load.sh --env dev --tables store_tasks` | Reload only the task table, so an approve or assign demo can run again |
| `uv run python quickstarts/02-rag-knowledge-agent/sop_data_store.py setup` | Create the store procedures data store in Vertex AI Search (`verify`, `teardown` also work) |

## Run the agent

| Command | What it does |
|---|---|
| `uv run adk web agents --port 8000` | The ADK developer UI at http://localhost:8000 |
| `uv run adk run agents/cymbal_store_ops` | Chat with the agent in the terminal |
| `uv run python frontend/server.py --target local --port 8080` | The tablet app over the local agent |
| `uv run python frontend/server.py --target agent-engine --env dev --port 8080` | The tablet app over your deployed engine |
| `uv run python scripts/quickstart_apps.py && uv run adk web build/quickstart_apps --port 8001` | The developer UI over the twelve quickstarts |

## Test and evaluate

| Command | What it does |
|---|---|
| `uv run pytest tests/unit tests/quickstarts -q` | Unit tests, no cloud access |
| `uv run pytest tests/integration -q -m live` | Live smoke test against your dataset |
| `uv run pytest tests/eval -q -k test_golden_gate_passes` | The evaluation gate: seven cases, two runs each |
| `STORE_OPS_FAULT=stale_stock uv run pytest tests/eval -q -k test_golden_gate_passes` | Break the gate on purpose with a stale feed (it must fail) |
| `uv run adk eval agents/cymbal_store_ops eval/evalsets/golden.evalset.json --config_file_path eval/evalsets/test_config.json --print_detailed_results` | The same cases through `adk eval`, with detail per case |
| `uv run python journeys/run.py --journey <id>` | One multi-turn conversation test ([journeys](../journeys/README.md)) |
| `uv run python eval/run_broad.py --run --target remote --judge` | The fifty broad questions against your deployed engine |
| `uv run python eval/benchmark_writer.py --levels inherit,low --judge` | Compare the plan writer's thinking levels |
| `uv run ruff check . && uv run python scripts/check_skills.py && uv run python scripts/check_docs.py` | Lint the code, the skills and the docs |

## Deploy

| Command | What it does |
|---|---|
| `uv run python deployment/release.py && uv run python deployment/deploy.py --env dev --release release.json` | Deploy to your dev engine on Agent Runtime; add `--dry-run` to print the configuration only |
| `uv run python deployment/mcp_deploy.py --help` | Build and deploy the MCP server the deployed agent reads through |
| `bash deployment/deploy_frontend.sh dev` | Deploy the tablet app to Cloud Run against your engine |
| `gcloud secrets versions access latest --secret=cymbal-frontend-$WORKSHOP_NAMESPACE-dev-password` | Print the tablet app's password |

Preprod and prod deploy only through the Cloud Build pipeline with approvals ([promotion](PROMOTION_STRATEGY.md)).

## Clean up

| Command | What it does |
|---|---|
| `uv run python scripts/resources.py` | List every resource that carries your namespace |
| `uv run python deployment/teardown.py --env dev --yes && bash data/teardown.sh --env dev --yes` | Delete your dev engine and dataset |
| `uv run python scripts/resources.py --delete --yes` | Delete everything in your namespace |
