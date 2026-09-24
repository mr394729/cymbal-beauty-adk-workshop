# Workshop diagrams

[Workshop home](../../README.md) · [Architecture](../ARCHITECTURE.md) · [Visual briefs](prompts/README.md)

Every diagram is a Gemini render in one house style, briefed from the code in [prompts/](prompts/README.md):
the workshop and store-agent visuals are the ones on the slides, and each quickstart has one of its own.

| Diagram | Purpose | Used by |
|---|---|---|
| [Workshop](workshop.png) | Open, follow, run, extend: the session and afterwards | README, notebook index |
| [Platform](platform.png) | Store team, ADK, Agent platform, governance, store data | Notebook 00 |
| [System](system.png) | Tablet app, one ADK app on Agent Runtime, Gemini, BigQuery, evaluation and traces | Architecture guide |
| [Capabilities](capabilities.png) | What the agent does for the manager and the associate | README |
| [Store agent architecture](store-agent-architecture.png) | Coordinator, specialists, workflows, tools and the checks around every step, by pattern | README, architecture guide, notebook 02 |
| [Patterns overview](patterns-overview.png) | The eight ADK patterns; blue tiles are in the store agent | Pattern pages |
| [Pattern 1–8](pattern-1-coordinator-and-dispatcher.png) | One diagram per pattern, numbered flow | [Pattern pages](../patterns/README.md), deck |
| [Explore the code](explore-the-code.png) | A reading order for the agent package | README |
| [Run options](run-options.png) | Laptop, Agent Runtime, any container | ADK developer UI guide |
| [Queries and reports](query-report.png) | The model chooses the query, code enforces the boundary, answer or report | Architecture guide, tools README, notebook 03 |
| [Sessions](sessions.png) | Who is signed in, one conversation, long-term memory as a separate service | Architecture guide |
| [Evaluation loop](evaluation-loop.png) | Cases, the agent, checks in code, a model judge, the gate | Evaluation guide |
| [Observability](observability.png) | Traces, logs and metrics, and what is kept out of them | Observability guide |
| [Agent lifecycle](agent-lifecycle.png) | The application pipeline and the agent pipeline, with the change review | Cloud Build README, promotion strategy, notebook 05 |
| [Release](release.png) | Promotion: dev, preprod, prod; approvals and traffic | Deployment README, architecture guide |
| [Governance map](governance-map.png) | Identity, access, actions, content, registry, observability around the agent | Governance guide |
| [Quickstart diagrams](../../quickstarts/README.md) | One per standalone quickstart, `q01.png`–`q12.png`: the person, the agent's job, the result | Quickstart READMEs and walkthroughs |

## Maintain or reuse

The PNGs are 1,800 px wide, palette-reduced for the repository. Each has a brief under [prompts/](prompts/)
with the description that produced it and the source files it was drawn from; regenerate a diagram by editing
its brief and rendering it with the gemini-diagramming pipeline described there. Check the linked code first:
the diagram must say what the code does.


The file-by-file history of earlier diagram sets is in [the diagram audit](../DIAGRAM_AUDIT.md).
