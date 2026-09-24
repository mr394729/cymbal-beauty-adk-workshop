# Automated checks

[Workshop home](../README.md) · [Evaluation guide](../eval/README.md) · [Notebook 04](../notebooks/04_evaluate_and_observe.ipynb)

The suites separate deterministic code checks from live agent behavior. Run the checks that match the
change, and read the evidence at that level: passing unit tests does not establish live answer quality.

| Suite | Checks | Run | Cloud required |
|---|---|---|---|
| [unit](unit/) | Tools, scope, confirmation, data, traces, UI contracts, evaluation metrics and notebook helpers | `uv run pytest tests/unit -q` | No |
| [quickstarts](quickstarts/) | Catalog structure and each example's own isolated unit suite | `uv run pytest tests/quickstarts -q` | No |
| [eval](eval/) | ADK evaluation thresholds against the dev fixture | `uv run pytest tests/eval -q -k test_golden_gate_passes` | Yes |
| [integration](integration/) | Real agent runs with BigQuery and Gemini | `uv run pytest tests/integration -q -m live` | Yes |
| [iam](iam/) | Denied operations using the configured test identities | `uv run pytest tests/iam -q -m live` | Yes |

## The normal local check

```bash
uv run pytest tests/unit tests/quickstarts -q
uv run ruff check . && uv run python scripts/check_skills.py && uv run python scripts/check_docs.py
```

`uv run pytest tests/unit tests/quickstarts -q` explicitly selects unit and quickstart suites. `uv run ruff check . && uv run python scripts/check_skills.py && uv run python scripts/check_docs.py` checks Python, documentation and skill
references. Prefer these targets over an unqualified `pytest`, which can collect cloud-dependent suites.
The `live` marker describes the requirement; a marker alone does not skip a test.

Tests use deterministic records for local checks. Quickstart suites run in separate processes because their
agent modules and environment requirements differ. Tests under `fixtures/` are recorded inputs, not cloud results.

## What CI runs

[GitHub Actions](../.github/workflows/) defines the repository checks and cloud evaluation job.
[Cloud Build](../cloudbuild/README.md) defines a separate source-check pipeline and deployment/promotion steps.
A pipeline file establishes the configuration; a successful build log establishes execution.

## Local cache folders

Pytest and Ruff cache results under ignored `build/cache/`. They are regenerable local files and are not
workshop material or part of the published repository.
