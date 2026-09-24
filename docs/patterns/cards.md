# Pattern presenter cards

[Pattern index](README.md) · [Card template](card-template.md) · [Quickstart notebooks](../../quickstarts/README.md)

Use each card as a short explanation beside its notebook and diagram. Demonstrate the actual tool or agent events, then change one user constraint and compare the result.

## 1. Choose the evidence needed

**Store need:** Compare product categories or find a lower-priced alternative.

**ADK pattern:** Model-selected function tools and structured queries.

**Flow:** Request → chosen fields and filters → scoped query → answer or report.

**Why use it:** New questions can use existing records without a dedicated scenario function.

**Consider:** A query can only answer from available sources; missing data remains unknown.

[Source](../../agents/cymbal_store_ops/tools/store_query.py) · [Notebook](../../notebooks/03_tools_and_workflows.ipynb) · [Visual](../diagrams/query-report.png)

## 2. Consult a specialist

**Store need:** Resolve an inventory dependency or coverage conflict.

**ADK pattern:** Single-turn specialist agent.

**Flow:** Coordinator → question and constraints → specialist reads → findings → answer.

**Why use it:** Separate instructions help with focused analysis.

**Consider:** Each consultation adds execution time; simple facts can use direct tools.

[Source](../../agents/cymbal_store_ops/sub_agents/inventory_excellence.py) · [Notebook](../../notebooks/02_agent_patterns.ipynb) · [Visual](../diagrams/store-agent-architecture.png)

## 3. Build an opening plan

**Store need:** Prioritize the work that needs attention at the start of the shift.

**ADK pattern:** Parallel code reads followed by sequential model synthesis.

**Flow:** Inventory, coverage and loss reads → selected facts → plan writer → briefing.

**Why use it:** Independent reads overlap while the writer receives one concise evidence set.

**Consider:** A fixed briefing workflow suits a recurring decision; it does not replace open-ended tool selection.

[Source](../../agents/cymbal_store_ops/sub_agents/daily_briefing.py) · [Notebook](../../notebooks/03_tools_and_workflows.ipynb) · [Visual](../diagrams/pattern-6-hierarchical-task-decomposition.png)

## 4. Continue a coaching conversation

**Store need:** Ask a development question and clarify the recommendation.

**ADK pattern:** Chat-agent hand-off.

**Flow:** Coordinator → development specialist → scoped learning/activity reads → follow-up.

**Why use it:** The specialist can continue the conversation with relevant context.

**Consider:** The active agent and user scope must remain correct across follow-ups.

[Source](../../agents/cymbal_store_ops/sub_agents/associate_development.py) · [Notebook](../../notebooks/02_agent_patterns.ipynb) · [Visual](../diagrams/q10.png)

## 5. Review a proposed action

**Store need:** Create or delegate a task, or update an associate’s own assigned work.

**ADK pattern:** Resumable execution with human confirmation.

**Flow:** Permitted request → proposed change → confirmation → guarded, idempotent write.

**Why use it:** The person reviews the action before it changes task records.

**Consider:** Confirmation does not replace role and ownership checks.

[Source](../../agents/cymbal_store_ops/tools/domain_tools.py) · [Notebook](../../notebooks/06_governance.ipynb) · [Visual](../diagrams/pattern-7-human-in-the-loop.png)

## 6. Deliver a detailed report

**Store need:** Inspect a complete matching inventory or review result set.

**ADK pattern:** Tool-produced UI state with bounded model context.

**Flow:** Chosen query → scoped records → searchable table and CSV → concise report summary.

**Why use it:** Rows stay available to the person without filling the model context.

**Consider:** Reports cap at 5,000 rows and disclose completeness. This table is distinct from an ADK file artifact.

[Source](../../agents/cymbal_store_ops/tools/report_delivery.py) · [Notebook](../../notebooks/03_tools_and_workflows.ipynb) · [Visual](../diagrams/query-report.png)

## 7. Read a document artifact

**Store need:** Check a promotion proof against the published plan.

**ADK pattern:** ADK artifacts, structured extraction and a bounded review loop.

**Flow:** Upload saved as artifact → extraction → review → deterministic plan comparison.

**Why use it:** The model reads the document while code checks the extracted values.

**Consider:** This is standalone quickstart 07; it reads a supplied document rather than generating a daily dashboard.

[Source](../../quickstarts/07-document-extraction-agent/agent.py) · [Notebook](../../notebooks/02_agent_patterns.ipynb) · [Visual](../diagrams/q07.png)

## 8. Retrieve a procedure

**Store need:** Find the procedure for pickup holds or a locked fragrance case.

**ADK pattern:** Retrieval-augmented generation through a search tool.

**Flow:** Procedure corpus → configured search data store → relevant snippets → sourced answer.

**Why use it:** Answers can refer to maintained procedures.

**Consider:** Requires a configured data store; an uncovered question should not become an invented policy.

[Source](../../quickstarts/02-rag-knowledge-agent/agent.py) · [Notebook](../../notebooks/03_tools_and_workflows.ipynb) · [Visual](../diagrams/q02.png)

## 9. Publish a recommendation from an event

**Store need:** Turn an availability exception into a message for downstream review.

**ADK pattern:** Event-shaped input and Pub/Sub output.

**Flow:** Exception JSON → stock evidence → recommendation → output topic.

**Why use it:** Demonstrates a machine-originated request and a structured downstream result.

**Consider:** Quickstart 11 is a publisher. The inbound subscriber and tablet notification inbox are separate outstanding integrations.

[Source](../../quickstarts/11-ambient-event-agent/agent.py) · [Notebook](../../notebooks/02_agent_patterns.ipynb) · [Visual](../diagrams/q11.png)

## 10. Keep conversation context

**Store need:** Refine an earlier question without repeating all its constraints.

**ADK pattern:** ADK sessions and recorded events.

**Flow:** User/session identity → messages and tool results → current request → updated state.

**Why use it:** Follow-ups can retain decisions, corrections and relevant references.

**Consider:** Local in-memory state is process-bound; a persistent history list in the tablet is a separate feature.

[Source](../../frontend/server.py) · [Notebook](../../notebooks/02_agent_patterns.ipynb) · [Visual](../diagrams/sessions.png)

## 11. Recall useful preferences

**Store need:** Remember how a manager prefers the morning huddle.

**ADK pattern:** User state plus memory ingestion and retrieval.

**Flow:** Preference update → session ingestion → configured memory service → later retrieval.

**Why use it:** Relevant preferences can be reused across conversations.

**Consider:** Demonstrated in standalone quickstart 06; durability depends on the configured services.

[Source](../../quickstarts/06-memory-agent/agent.py) · [Notebook](../../notebooks/02_agent_patterns.ipynb) · [Visual](../diagrams/q06.png)

## 12. Evaluate and inspect a run

**Store need:** Understand the answer and decide whether a candidate is ready.

**ADK pattern:** Recorded execution spans and factual/model-based evaluation.

**Flow:** Question → agent and tool events → answer checks → release review.

**Why use it:** Trace evidence helps locate factual drift, repeated calls and time spent.

**Consider:** A trace proves execution, not answer quality; evaluation evidence belongs to the tested revision.

[Source](../../eval/README.md) · [Notebook](../../notebooks/04_evaluate_and_observe.ipynb) · [Visual](../diagrams/agent-lifecycle.png)
