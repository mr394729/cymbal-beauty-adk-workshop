# Notebook labs

[Workshop home](../README.md) · [Cloud setup](../SETUP.md) · [Quickstarts](../quickstarts/README.md)

Eight notebooks take you through the store agent in the order of the workshop. They use the same data, tools and
agent as the tablet app. Each one follows the layout of the Google Cloud generative AI sample notebooks: an
overview of the concepts, the objectives and costs, a setup cell for your project and namespace, and then one step
at a time, with a short explanation before each code cell. Every cell calls the SDK directly: ADK, the Gen AI SDK,
BigQuery and the Agent Runtime (formerly Agent Engine) client.

| Notebook | What you do |
|---|---|
| [00 · Get started with the workshop and the agent platform](00_workspace_and_platform.ipynb) | Check your packages, call Gemini on Vertex AI, read the agent's configuration for each environment and send a question to the deployed agent. |
| [01 · Explore and load the store data](01_store_data.ipynb) | Generate and profile the thirteen tables, look at one store's stock and trading history, load the tables into BigQuery in your namespace, give your agent access and query the data with SQL. |
| [02 · Multi-agent patterns in the Cymbal Beauty store agent](02_agent_patterns.ipynb) | Build the agent tree and read how each sub-agent joins in, see a specialist consulted as a tool, see three readers run in parallel before one writer, and build a sequential pipeline. |
| [03 · Tools, reports and sessions in the store agent](03_tools_and_workflows.ipynb) | Read the declaration the model receives for a tool, call the tools directly, see the store and role boundary inside a tool, deliver a large result as a report and CSV, and keep state across turns in a session. |
| [04 · Evaluate and observe the store agent](04_evaluate_and_observe.ipynb) | Read the gate's cases and thresholds, score answers with a custom metric, run the gate with `AgentEvaluator`, run a multi-turn conversation test, draw a turn's spans on a timeline and publish results to Vertex AI evaluation. |
| [05 · Deploy the store agent to Agent Runtime and promote a release](05_deploy_and_promote.ipynb) | Package the agent, create or update your engine, query it and list its sessions, split traffic between two revisions and read the Cloud Build release pipeline. |
| [06 · Governance controls for the store agent](06_governance.ipynb) | See scope and role checks refuse requests, test the SQL guard, stop at a task confirmation, screen prompts and answers with Model Armor and list Agent Registry entries. |
| [07 · Measure the tokens, time and cost of an agent turn](07_cost_and_tokens.ipynb) | Record every model call in a turn, price a turn and a month of use, compare thinking levels and read BigQuery costs from the job history. |

## Open the notebooks

From the repository root:

```bash
uv sync --all-extras
uv run jupyter lab notebooks/
```

**Check.** JupyterLab opens in the `notebooks/` folder. Open notebook 00 with the repository's `.venv` Python kernel. The setup
cell in each notebook adds the repository root to the Python path, so keep the notebooks inside the checkout.

If the kernel can't find the installed packages, register the environment and select **Python 3 (Cymbal
workshop)**:

```bash
uv run python -m ipykernel install --user --name cymbal-workshop --display-name "Python 3 (Cymbal workshop)"
```

**Check.** The kernel appears in Jupyter's kernel selector.

## Your project and namespace

Every notebook starts with the same cell: set `PROJECT_ID` and `WORKSHOP_NAMESPACE`, or leave the placeholders
and the cell reads `GOOGLE_CLOUD_PROJECT` and `WORKSHOP_NAMESPACE` from your environment. The namespace keeps your
BigQuery dataset, your engine and your other resources apart from everyone else's in a shared project. Choose one
before the session with `uv run python scripts/namespace.py`, as described in [SETUP.md](../SETUP.md).

The notebooks never touch another namespace. Notebook 05 deploys only your own engine, and nothing deploys to
preprod or production.

The notebooks are committed with outputs cleared, like the Google Cloud samples. To change one, read the
[notebook style guide](../docs/NOTEBOOK_AUTHORING.md).
