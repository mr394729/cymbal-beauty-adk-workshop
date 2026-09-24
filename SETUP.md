# Cloud setup

[Workshop home](README.md) · [Notebook 00](notebooks/00_workspace_and_platform.ipynb) · [Notebook 01](notebooks/01_store_data.ipynb)

Setup happens in a terminal, before any notebook opens. The notebooks then take over: notebook 00 checks that you
can reach Gemini and Agent Runtime, and notebook 01 loads your store data into BigQuery.

You need Python 3.12, [uv](https://docs.astral.sh/uv/), Git and the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install).
In the workshop everyone shares one project that is already prepared. With your own project, follow the
[shared project guide](docs/SHARED_PROJECT.md) first to enable the APIs and grant the roles.

## 1. Clone and install

```bash
git clone https://github.com/mr394729/cymbal-beauty-adk-workshop.git
cd cymbal-beauty-adk-workshop
uv sync --all-extras
```

**Check.** `uv sync` ends without errors. It installs the agent, the notebooks' packages and JupyterLab from `uv.lock`.

## 2. Sign in

```bash
gcloud auth login
gcloud auth application-default login
```

**Check.** Each command reports the account you signed in with. The first sign-in is for the `gcloud` tool. The second gives the Python client libraries their credentials
(Application Default Credentials). In Vertex AI Workbench or Cloud Shell you are already signed in.

## 3. Choose your project and namespace

```bash
cp .env.example .env
```

**Check.** `.env` exists in the repository root. Set `GOOGLE_CLOUD_PROJECT` in `.env` to the workshop project. Then choose a namespace: 3–12 lowercase letters and
digits, starting with a letter, such as your initials. Your dataset, agent and templates all carry it, so several
people can share one project.

```bash
uv run python scripts/namespace.py --set <yours>
uv run python scripts/check_env.py --stage prereqs
```

**Check.** Every prerequisite check passes. A failed check prints the command that fixes it.

## 4. Open the notebooks

```bash
uv run jupyter lab notebooks/
```

Open notebook 00 with the repository's Python kernel and run it, then run notebook 01. Notebook 01 writes the
store tables to your BigQuery dataset, and every later notebook reads them. Kernel troubleshooting is in the
[notebook guide](notebooks/README.md#open-the-notebooks).

**Check.** After notebook 01, the readiness check passes:

```bash
uv run python scripts/check_env.py --stage ready
```

## Afterwards: the tablet app on your machine

```bash
uv run python frontend/server.py --target local --port 8080
```

**Check.** Open the printed URL and choose a persona. The [tablet guide](frontend/README.md) explains activity, traces,
confirmations and reports. `uv run adk web agents --port 8000` opens the ADK developer UI instead.

To reload your data without Jupyter, for example after changing a generator:

```bash
uv run python data/generate.py && bash data/load.sh --env dev
```

**Check.** Each table reports its row count. The load replaces the tables in your namespace's dataset.

## Optional services

| Capability | Setup reference |
|---|---|
| Procedure retrieval | [RAG quickstart](quickstarts/02-rag-knowledge-agent/README.md) |
| Runtime deployment | [Notebook 05](notebooks/05_deploy_and_promote.ipynb) and [deployment](deployment/README.md) |
| Build and promotion | [Cloud Build](cloudbuild/README.md); requires a source connection, identities and triggers |
| Developer skills | [Skills](skills/README.md); optional, independent of the notebooks |
