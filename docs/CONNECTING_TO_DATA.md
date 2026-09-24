# Connecting agents to data: BigQuery live, anything else the same way

![Data access reference](diagrams/query-report.png)

The agents in this repository never talk SQL to the model. Their tools are a **contract**: a fixed
signature, a fixed return envelope (`{"status": "SUCCESS", "rows": [...]}` or
`{"status": "ERROR", "error_details": "..."}`), and a deterministic guard in front of anything that
looks like a query. Where the data lives is a detail behind that contract. In the workshop it is BigQuery,
because that is where the data is; the same contract reaches any other source without an agent change.

What an example dataset needs per use case, and how to point the agents at your own data: [DATA_REQUIREMENTS.md](DATA_REQUIREMENTS.md).

## Three ways to expose a source, and where the governance sits

| Way | Governance lives in | In this repo |
|---|---|---|
| Native ADK toolset (`BigQueryToolset`) | agent code + IAM: `WriteMode.BLOCKED`, `max_query_result_rows`, `job_labels`, dataset-level `dataViewer` | `agents/*/tools/backends/bigquery.py` |
| MCP Toolbox for Databases | `tools.yaml`: `writeMode: blocked`, `allowedDatasets`; the agent only sees tools | `quickstarts/08-mcp-tools-agent/toolbox/tools.yaml` |
| Any MCP server (yours or a platform's) | the server, plus Agent Registry (which servers are approved) and Agent Gateway (what leaves the agent) | `quickstarts/08-mcp-tools-agent/`, `quickstarts/08-mcp-tools-agent/` |

## The "connects to anything" pattern

`McpToolset` is the only line that changes. A local server over stdio:

```python
McpToolset(connection_params=StdioConnectionParams(server_params=StdioServerParameters(
    command="uv", args=["run", "python", "quickstarts/08-mcp-tools-agent/cymbal_mcp_server.py"])))
```

A remote server over Streamable HTTP — MCP Toolbox, a partner's endpoint, or another data platform's managed
MCP server (Databricks exposes one at `https://<workspace>/api/2.0/mcp/sql`, for example; Nilesh Jaiswal's
[article](https://medium.com/google-cloud/building-ai-agents-for-databricks-with-model-context-protocol-mcp-and-adk-a6db761c3168)
walks through exactly that shape with ADK):

```python
McpToolset(
    connection_params=StreamableHTTPConnectionParams(url=SERVER_URL, timeout=30),
    tool_filter=["execute_sql"],
    header_provider=lambda ctx: {"Authorization": f"Bearer {token_for(ctx)}"},  # rotating tokens are fine
)
```

The agent's prompts, evals and guardrails do not know which server answered. What does change per source is
the evidence you keep: on BigQuery it is `job_labels` plus `INFORMATION_SCHEMA.JOBS_BY_USER` (an attendee's own jobs) or `JOBS_BY_PROJECT` (everyone's; needs `bigquery.jobs.listAll`)
(`scripts/evidence.py`); another platform has its own query history and lineage tables, and the same approach applies when inspecting platform evidence.

## Conversational Analytics over the same data

`BigQueryToolset` also carries `ask_data_insights`, the Conversational Analytics capability: a governed
natural-language question over a table, answered with the query it ran. The [data analyst source example](../quickstarts/05-data-analyst-agent/README.md) uses it. It is the shortest path from "the data is in BigQuery" to "a business user can ask it a question"
without writing a data agent yourself.

## Documents: Vertex AI Search behind the same contract

Store procedures are documents, not tables. They live in one Vertex AI Search data store
(`cymbal-store-sops-<namespace>`, created by `uv run python quickstarts/02-rag-knowledge-agent/sop_data_store.py setup`), and the agent reaches them through `policy_lookup`, a
function tool with the same shape as every other tool: one argument, a `{"status": "SUCCESS", "rows": [...]}`
envelope of titles and snippets, and a raised error with the fix when the data store is missing or broken.

```python
DiscoveryEngineSearchTool(data_store_id=SOP_DATA_STORE, max_results=5, search_result_mode=SearchResultMode.CHUNKS)
```

The search is an explicit tool call, so it shows in Events, traces and eval trajectories. The tool is registered only
when `SOP_DATA_STORE` is set; `quickstarts/02-rag-knowledge-agent` is the smallest agent that uses it.

## Further reading

- BigQuery tools in ADK: https://adk.dev/integrations/bigquery/
- Vertex AI Search parsing and chunking: https://docs.cloud.google.com/generative-ai-app-builder/docs/parse-chunk-documents
- MCP in ADK: https://adk.dev/mcp/ · MCP Toolbox for Databases: https://adk.dev/integrations/mcp-toolbox-for-databases/
- Agent Registry (catalog of approved MCP servers, tools and agents): https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/agent-registry
- Agent Gateway: https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/gateways/agent-gateway-overview
