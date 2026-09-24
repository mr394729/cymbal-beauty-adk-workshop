# Hierarchical task decomposition

[All patterns](README.md) · [Previous: Iterative refinement](05-iterative-refinement.md) · [Next: Human-in-the-loop](07-human-in-the-loop.md)

![Hierarchical task decomposition](../diagrams/pattern-6-hierarchical-task-decomposition.png)

**ADK docs:** [Hierarchical task decomposition](https://adk.dev/workflows/patterns/#hierarchical-task-decomposition) · [Agent-as-a-Tool](https://adk.dev/tools-custom/function-tools/#agent-tool)

**What it is.** The coordinator hands a multi-step task to a workflow of agents and calls that workflow as one tool,
through `AgentTool`.

**Agentic flow**

1. The root calls the `daily_briefing` tool.
2. Behind the tool, a `SequentialAgent` starts.
3. Its first stage is a `ParallelAgent` with three branches.
4. Its second stage, `plan_writer`, produces a structured briefing.
5. The root receives one tool result.

**A good fit when**

- A task has several stages, and the caller only needs the result.
- More than one assistant should be able to reuse the same workflow.
- A team owns the workflow and may rebuild it without changing how it is called.

**Design alternatives**

- Sub-agents directly on the root when the model should choose between them.
- A separately deployed agent over A2A when another team releases it on its own schedule. See [quickstart 12](../../quickstarts/12-a2a-agent/README.md).

**Considerations**

- Workflow agents have no operating mode, so `AgentTool` is how a coordinator calls one.
- `AgentTool` is not a state boundary. The workflow is seeded with the caller's state and its state changes flow back. `temp:` keys end with the invocation; `action_plan` persists.
- When the briefing is the only tool call in the turn, the writer's text is delivered as the reply, with no second model call by the root.

**In our build**

| | |
|---|---|
| Tool | `make_daily_briefing_tool` wraps the `daily_briefing` workflow |
| Source | [`sub_agents/daily_briefing.py`](../../agents/cymbal_store_ops/sub_agents/daily_briefing.py) |
| Try it | In the tablet app, ask "What should I be on top of first?" and open **Agent activity → View trace**. The root shows one `daily_briefing` call with the workflow's spans nested under it. |
| Related | [Parallel fan-out and gather](04-parallel-fan-out.md) describes what runs inside the tool. |
