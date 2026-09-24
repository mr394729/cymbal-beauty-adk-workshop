# Diagram audit

[Current visual library](diagrams/README.md) · [Repository QA](REPOSITORY_QA.md)

Two diagram sets have been retired. The first raster set mixed earlier architecture, generic patterns and
standalone examples; it was replaced by SVGs rendered from source descriptions. On 22 September 2026 the
eleven workshop and store-agent SVGs were replaced in turn by the workshop deck's Gemini visuals, drawn from
the current code in one house style (see the [diagram index](diagrams/README.md)); the twelve quickstart SVGs
remain. The table maps each removed image to what stands in its place today.

| Removed image | Current visual | Previous references |
|---|---|---|
| `q11-ambient-event-agent.png` | [q11](diagrams/q11.png) | docs/diagrams/README.md, quickstarts/11-ambient-event-agent/README.md |
| `08-usecase-next-best-action.png` | [q10](diagrams/q10.png) | docs/diagrams/README.md |
| `10-pattern-gallery.png` | [store-agent-architecture](diagrams/store-agent-architecture.png) | docs/diagrams/README.md, notebooks/02_agent_patterns.ipynb |
| `17-trace-anatomy.png` | [observability](diagrams/observability.png) | docs/OBSERVABILITY.md, docs/diagrams/README.md |
| `q10-multi-agent-router.png` | [q10](diagrams/q10.png) | docs/diagrams/README.md, quickstarts/10-multi-agent-router/README.md |
| `14-evalset-anatomy.png` | [agent-lifecycle](diagrams/agent-lifecycle.png) | docs/diagrams/README.md |
| `p5-loop-generate-review.png` | [q07](diagrams/q07.png) | No active reference |
| `p1-coordinator.png` | [store-agent-architecture](diagrams/store-agent-architecture.png) | No active reference |
| `13-hitl-confirmation-flow.png` | [pattern-7-human-in-the-loop](diagrams/pattern-7-human-in-the-loop.png) | docs/diagrams/README.md |
| `q02-rag-knowledge-agent.png` | [q02](diagrams/q02.png) | docs/diagrams/README.md, quickstarts/02-rag-knowledge-agent/README.md |
| `07-usecase-store-manager.png` | [store-agent-architecture](diagrams/store-agent-architecture.png) | docs/diagrams/README.md |
| `a6-store-tasks.png` | [pattern-7-human-in-the-loop](diagrams/pattern-7-human-in-the-loop.png) | docs/diagrams/README.md |
| `01-store-ops-agent-tree.png` | [store-agent-architecture](diagrams/store-agent-architecture.png) | docs/diagrams/README.md |
| `12-operating-modes.png` | [q10](diagrams/q10.png) | docs/diagrams/README.md |
| `q12-a2a-agent.png` | [q12](diagrams/q12.png) | docs/diagrams/README.md, quickstarts/12-a2a-agent/README.md |
| `19-skill-progressive-disclosure.png` | [workshop](diagrams/workshop.png) | docs/diagrams/README.md |
| `20-governance-plane.png` | [platform](diagrams/platform.png) | docs/diagrams/README.md |
| `24-platform-in-context.png` | [platform](diagrams/platform.png) | notebooks/00_workspace_and_platform.ipynb |
| `a9-guardrails-map.png` | [pattern-7-human-in-the-loop](diagrams/pattern-7-human-in-the-loop.png) | docs/diagrams/README.md |
| `p2-agent-as-a-tool.png` | [q10](diagrams/q10.png) | No active reference |
| `18-attendee-paths.png` | [workshop](diagrams/workshop.png) | docs/diagrams/README.md |
| `q09-guardrails-agent.png` | [q09](diagrams/q09.png) | docs/diagrams/README.md, quickstarts/09-guardrails-agent/README.md |
| `06-cicd-promotion.png` | [release](diagrams/release.png) | docs/diagrams/README.md, notebooks/05_deploy_and_promote.ipynb |
| `a11-mcp-server.png` | [q08](diagrams/q08.png) | docs/diagrams/README.md |
| `a8-policy-lookup-retrieval.png` | [q02](diagrams/q02.png) | docs/diagrams/README.md |
| `q07-document-extraction-agent.png` | [q07](diagrams/q07.png) | docs/diagrams/README.md, quickstarts/07-document-extraction-agent/README.md |
| `15-promotion-ladder.png` | [agent-lifecycle](diagrams/agent-lifecycle.png) | docs/diagrams/README.md |
| `a0-system-architecture.png` | [system](diagrams/system.png) | docs/diagrams/README.md |
| `a3-associate-orchestration.png` | [store-agent-architecture](diagrams/store-agent-architecture.png) | docs/diagrams/README.md |
| `11-callback-lifecycle.png` | [q09](diagrams/q09.png) | docs/diagrams/README.md |
| `a2-inventory-excellence.png` | [query-report](diagrams/query-report.png) | docs/diagrams/README.md |
| `02-sub-agents-vs-agenttool.png` | [q10](diagrams/q10.png) | docs/diagrams/README.md |
| `q08-mcp-tools-agent.png` | [q08](diagrams/q08.png) | docs/diagrams/README.md, quickstarts/08-mcp-tools-agent/README.md |
| `p8-workflow-graph.png` | [q10](diagrams/q10.png) | No active reference |
| `q01-hello-tool-agent.png` | [q01](diagrams/q01.png) | docs/diagrams/README.md, quickstarts/01-hello-tool-agent/README.md |
| `05-eval-loop.png` | [agent-lifecycle](diagrams/agent-lifecycle.png) | docs/diagrams/README.md |
| `q03-form-completion-agent.png` | [q03](diagrams/q03.png) | docs/diagrams/README.md, quickstarts/03-form-completion-agent/README.md |
| `q05-data-analyst-agent.png` | [q05](diagrams/q05.png) | docs/diagrams/README.md, quickstarts/05-data-analyst-agent/README.md |
| `a5-associate-development.png` | [store-agent-architecture](diagrams/store-agent-architecture.png) | docs/diagrams/README.md |
| `a1-store-manager-agent.png` | [store-agent-architecture](diagrams/store-agent-architecture.png) | docs/diagrams/README.md |
| `q04-external-api-agent.png` | [q04](diagrams/q04.png) | docs/diagrams/README.md, quickstarts/04-external-api-agent/README.md |
| `03-session-state-model.png` | [sessions](diagrams/sessions.png) | docs/diagrams/README.md |
| `p3-sequential-pipeline.png` | [pattern-6-hierarchical-task-decomposition](diagrams/pattern-6-hierarchical-task-decomposition.png) | No active reference |
| `a10-shared-project-namespacing.png` | [system](diagrams/system.png) | docs/diagrams/README.md |
| `a4-loss-prevention.png` | [store-agent-architecture](diagrams/store-agent-architecture.png) | docs/diagrams/README.md |
| `q06-memory-agent.png` | [q06](diagrams/q06.png) | docs/diagrams/README.md, quickstarts/06-memory-agent/README.md |
| `a7-daily-briefing-internals.png` | [pattern-6-hierarchical-task-decomposition](diagrams/pattern-6-hierarchical-task-decomposition.png) | docs/diagrams/README.md |
| `22-daily-briefing-flow.png` | [pattern-6-hierarchical-task-decomposition](diagrams/pattern-6-hierarchical-task-decomposition.png) | docs/diagrams/README.md |
| `23-traceability-chain.png` | [pattern-7-human-in-the-loop](diagrams/pattern-7-human-in-the-loop.png) | docs/diagrams/README.md, notebooks/06_governance.ipynb |
| `04-data-access-reference.png` | [query-report](diagrams/query-report.png) | docs/CONNECTING_TO_DATA.md, docs/diagrams/README.md |

## SVGs retired on 22 September 2026

| Removed SVG | Current visual |
|---|---|
| `current/agent-composition.svg` | [store-agent-architecture](diagrams/store-agent-architecture.png) |
| `current/daily-briefing.svg` | [pattern-6-hierarchical-task-decomposition](diagrams/pattern-6-hierarchical-task-decomposition.png) |
| `current/reviewed-actions.svg` | [pattern-7-human-in-the-loop](diagrams/pattern-7-human-in-the-loop.png) |
| `current/agent-lifecycle.svg` | [agent-lifecycle](diagrams/agent-lifecycle.png) |
| `current/release.svg` | [release](diagrams/release.png) |
| `current/system.svg` | [system](diagrams/system.png) |
| `current/platform.svg` | [platform](diagrams/platform.png) |
| `current/workshop.svg` | [workshop](diagrams/workshop.png) |
| `current/trace.svg` | [observability](diagrams/observability.png) |
| `current/query-report.svg` | [query-report](diagrams/query-report.png) |
| `current/sessions.svg` | [sessions](diagrams/sessions.png) |

## Quickstart SVGs retired on 22 September 2026

`current/q01.svg`–`current/q12.svg` and `scripts/render_workshop_diagrams.py` are replaced by `docs/diagrams/q01.png`–`q12.png`, Gemini renders in the same house style as the workshop diagrams, briefed in `docs/diagrams/prompts/q01.md`–`q12.md`.
