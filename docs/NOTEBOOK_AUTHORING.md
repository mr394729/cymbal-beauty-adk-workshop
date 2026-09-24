# Notebook style guide

[Workshop home](../README.md) · [Notebook labs](../notebooks/README.md) · [Quickstarts](../quickstarts/README.md)

The lab notebooks and the quickstart walkthroughs follow the style of the Google Cloud generative AI samples, for
example [Intro to building and deploying an agent](https://github.com/GoogleCloudPlatform/generative-ai/blob/main/gemini/agent-engine/intro_agent_engine.ipynb).
Edit the notebooks directly in JupyterLab. `tests/unit/test_notebook_style.py` checks the rules below that code can
check.

## Structure

Every notebook has these parts, in this order:

1. A code cell with the Apache 2.0 licence header.
2. The title as a `#` heading, in sentence case, and the author table.
3. `## Overview`, with `###` subsections that explain the concepts, each linking the Google documentation page.
   One diagram from `docs/diagrams/`, as an HTML image tag with `width="60%"`, a `src` under `../docs/diagrams/`
   and alt text. Keep images between 40 and 60 percent wide.
4. `### Objectives`: "In this tutorial, you will learn ..." followed by "You will complete the following tasks:"
   and a bulleted list.
5. `### Costs`: the billable products, with links to their pricing pages.
6. `## Get started`: `### Set Google Cloud project information`, the same `PROJECT_ID` and `WORKSHOP_NAMESPACE`
   cell in every notebook, then `### Import libraries`.
7. The task sections as `##` headings and steps as `###` headings. Every code cell has one short paragraph before
   it that says what the cell does and why.
8. `## Cleaning up`: the code that deletes what the notebook created, or a sentence saying it creates nothing.
9. `## What's next`: links to the documentation and to the next notebook.

## Code

- Put the call that does the work in the cell: `google.adk`, `google.genai`, `google.cloud.bigquery`,
  `vertexai`, `google.cloud.modelarmor_v1` and so on. The reader must see the SDK call.
- Import from the repository only the thing being taught: the agent through `create_app(log_events=False)`, a tool
  function, the data generator.
- A small helper is fine when it is defined in the notebook, visible, with a docstring.
- No `make` targets, no subprocess wrappers around repository scripts, no run flags, no custom HTML or CSS.
- A cell that takes a while or costs money says so in the paragraph before it.
- Show example prompts under "Try these example phrases:" in a fenced block.
- Put warning filters in their own cell before the imports, so the notebook passes `ruff`.

## Voice

- Google developer documentation voice: second person, present tense, plain words, short sentences.
- Explain what happens and why, in concrete terms. No slogans, no inflated words such as "robust", "seamless" or
  "leverage", and no commentary about AI.
- Use the workshop's names: Cymbal Beauty, store S-014, Dana (store manager, U-M014), Priya (associate, A-1004).

## Before you commit

Run the notebook top to bottom from the `notebooks/` folder against your own namespace and read every output:

```bash
cd notebooks
GOOGLE_CLOUD_PROJECT=<project> WORKSHOP_NAMESPACE=<namespace> \
  uv run jupyter nbconvert --to notebook --execute 02_agent_patterns.ipynb --output /tmp/02_agent_patterns.ipynb
```

Then clear the outputs and run the checks:

```bash
uv run jupyter nbconvert --clear-output --inplace notebooks/02_agent_patterns.ipynb
uv run ruff check notebooks
uv run pytest tests/unit/test_notebook_style.py -q
```
