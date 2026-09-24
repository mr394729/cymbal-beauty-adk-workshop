# Explore ADK one pattern at a time

[Workshop home](../README.md) · [Notebook 02](../notebooks/02_agent_patterns.ipynb)

Each example has a short notebook walkthrough, source, unit tests and an ADK evaluation set. Use it to
understand one capability before looking at how the store application combines them.

| Pattern | Notebook | Source guide | Services for the live example |
|---|---|---|---|
| Function tools | [Walkthrough](01-hello-tool-agent/walkthrough.ipynb) | [Guide](01-hello-tool-agent/README.md) | Gemini and BigQuery |
| Procedure retrieval / RAG | [Walkthrough](02-rag-knowledge-agent/walkthrough.ipynb) | [Guide](02-rag-knowledge-agent/README.md) | Gemini and configured Vertex AI Search data store |
| Form completion and confirmation | [Walkthrough](03-form-completion-agent/walkthrough.ipynb) | [Guide](03-form-completion-agent/README.md) | Gemini and product data; submission returns a record without writing it |
| External APIs | [Walkthrough](04-external-api-agent/walkthrough.ipynb) | [Guide](04-external-api-agent/README.md) | Gemini, local order API and weather endpoint |
| BigQuery analytics tools | [Walkthrough](05-data-analyst-agent/walkthrough.ipynb) | [Guide](05-data-analyst-agent/README.md) | Gemini, BigQuery and analytics permissions |
| State and memory | [Walkthrough](06-memory-agent/walkthrough.ipynb) | [Guide](06-memory-agent/README.md) | Gemini; persistence depends on selected memory/session services |
| Artifacts, extraction and review | [Walkthrough](07-document-extraction-agent/walkthrough.ipynb) | [Guide](07-document-extraction-agent/README.md) | Gemini and the supplied document fixture |
| Tools over MCP | [Walkthrough](08-mcp-tools-agent/walkthrough.ipynb) | [Guide](08-mcp-tools-agent/README.md) | Gemini, BigQuery and bundled local stdio server |
| Callbacks and plugins | [Walkthrough](09-guardrails-agent/walkthrough.ipynb) | [Guide](09-guardrails-agent/README.md) | Gemini and store data |
| Specialists and workflows | [Walkthrough](10-multi-agent-router/walkthrough.ipynb) | [Guide](10-multi-agent-router/README.md) | Gemini and store data |
| Event-shaped input and publishing | [Walkthrough](11-ambient-event-agent/walkthrough.ipynb) | [Guide](11-ambient-event-agent/README.md) | Gemini, stock data and Pub/Sub output topic |
| Agent-to-agent delegation | [Walkthrough](12-a2a-agent/walkthrough.ipynb) | [Guide](12-a2a-agent/README.md) | Gemini and separately running A2A service |

## Run locally

The notebook walkthroughs inspect source and sample evaluation questions without cloud calls.
Run all example unit suites with:

```bash
uv run pytest tests/quickstarts -q
```

For live conversations, complete [cloud setup](../SETUP.md), follow the selected guide's service prerequisites,
then run `uv run python scripts/quickstart_apps.py && uv run adk web build/quickstart_apps --port 8001`. Choose `qs_<number>_<name>` in the ADK developer UI.

These examples import shared code from this repository, so keep them inside the checkout. They are focused
teaching examples, not independent production services. In particular, example 11 publishes recommendations;
it does not supply the tablet notification workflow. Example 08 uses local stdio MCP, not hosted Cloud Run MCP.

## Evaluate the live examples

`uv run python scripts/eval_quickstarts.py` runs their ADK evaluation sets sequentially and writes `build/quickstart_evals.md`.
It calls cloud services; missing prerequisites are errors. The [repository QA](../docs/REPOSITORY_QA.md) records
what was checked in this documentation pass. Offline tests and older live logs do not prove current live success.

For broader examples, see [ADK samples](https://github.com/google/adk-samples).
