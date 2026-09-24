# Coding agent guide — the store operations package

| Node | Kind / mode | Tools | State it writes |
|---|---|---|---|
| `store_manager_agent` | LlmAgent, chat root | Identity/clock, guest and merchandising reads, own-work reads and confirmed updates, whole-store inventory summary/pages, `describe_store_data`, `query_store_data`, `daily_briefing` (AgentTool), optional `policy_lookup`, specialist and task agents | `user:*`, `action_plan`, `ui:next_actions`, `ui:report` |
| `daily_briefing` | `SequentialAgent[ParallelAgent(3 BriefingSignals code branches) → plan_writer]` behind `AgentTool` | Fixed scoped inventory, coverage and loss reads; deterministic fact projection; writer returns a compact `BriefingDraft`; a code finalizer supplies trusted metadata and preserves canonical `BriefingReply` (ActionPlan + dynamic next actions). A sole successful call delivers it without another model rewrite. | `temp:briefing_*` (invocation only), `action_plan`, `ui:next_actions` |
| `inventory_excellence` | `mode="single_turn"`, `input_schema=OsaQuery` | Whole-store summary/pages, schema discovery and structured queries, product inventory context, focused stock/location/order/supply/task and nearby-stock reads | `last_osa`, `ui:report` |
| `associate_orchestration` | `mode="single_turn"`, `input_schema=CoverageQuery` | Clock, traffic/backlog, roster, coverage requirements, pickup workload, schema discovery and structured queries | `last_coverage`, `ui:report` |
| `loss_prevention` | `mode="single_turn"`, `input_schema=ShrinkQuery` | Product search, loss signals, store sales pattern, task history, controls, reconciliation, schema discovery and structured queries | `last_shrink`, `ui:report` |
| `associate_development` | chat sub-agent (transfer) | `get_coaching_context`, `get_learning_options` (manager/team or associate/self scope) | `ui:next_actions` |
| `store_tasks` | `mode="task"` | Clock, task status, `create_store_task` and `delegate_task` with confirmation | `writes:<invocation>`; `task_key` = hash of the write |

Invariants:
- `agent.py` exports both `root_agent` and `app` (`App` with `IngressRedactionPlugin`, `LoggingPlugin`,
  `ResumabilityConfig(is_resumable=True)`, a context cache). `adk web`, `adk eval` and `deployment/deploy.py` all load it.
- Every agent is built by a factory (`make_*`); never share instances between trees. The briefing builds its own
  branch instances; the root's single_turn agents are separate instances of the same kind.
- Behaviour lives in `prompts/*.md` (`{{PLACEHOLDERS}}` rendered from config; ADK's `{user:store_id?}` left intact).
- Identity and store scope come from session state (`user:*`, seeded by `identify_demo_user` in the lab and by the
  app at session creation in production), never from chat text or tool arguments.
- The model selects tools and reasons from their results. Tools supply records, aggregates and bounded calculations;
  scenarios do not prescribe a tool path. Corrections and the current user request control the scope.
- Manager writes are `create_store_task` (optional reviewed deadline) and `delegate_task`, behind confirmation and an idempotency key.
- Associates use `get_my_work`, self-scoped development/learning reads `complete_my_task` and `report_my_task_blocker`. Each write checks store and assignee in the write predicate, requires confirmation, and is idempotent. It does not move inventory or change order status.
- `operations_context` supplies source snapshots through the backend. Raw SQL cannot read this table because it contains personal development records.
- BriefingSignals collects fixed read inputs concurrently with scope/role guards and real call/result events.
  `briefing_facts.py` removes duplicate supporting rows while retaining decision-relevant facts and errors;
  the writer receives those facts once plus the caller’s request. Full results remain in session events and trace.
- `context_history.py` removes completed consultant internals from subsequent model input by event provenance;
  it retains the consultant result and conversation context without deleting the recorded events.
- `store_query.py` supports inventory, orders, tasks, traffic, loss, feedback, reviews, deliveries and roster. Identifiers
  are allowlisted, values parameterized and store/role checks enforced in code. Associates see only their assigned
  task records; loss requires a manager. It exposes no raw SQL or personal-development resource.
- Structured answer queries return 1–100 rows per page with counts computed before pagination. Report queries
  write up to 5,000 rows to `ui:report` and return metadata only. The frontend displays the full matching count
  and completeness; a capped report must not be described as complete.
- The root exposes catalog search and exact-product details. Details return the latest three dated reviews,
  their selection basis and the number of all stored reviews. Catalog rating average/count and this sample
  are distinct evidence. Joined structured-query fields include fragrance-free status, nullable skin-type and
  ingredient text, and rating aggregates. The separate `reviews` resource supports chosen filters, aggregates
  and reports over existing review records, scoped by product membership in the store’s inventory. It includes
  zero-stock members; catalog-wide reviewers are not this store’s guests. Individual review `rating` differs
  from catalog `rating_avg`/`rating_count`; neither establishes guest suitability.
- Blocking reads use `concurrent_read` to permit real parallel I/O. Write/confirmation tools stay on the invocation thread.
- `ChatReplyPlugin` separates readable answers from 3–5 suggested activities stored in `ui:next_actions`; pure refusals and cancellations clear those activities.
- Tool names, argument names and `output_key`s are contracts with `eval/` and `tests/`.
- `tool_context: ToolContext | None = None` is always the **last** parameter of a domain tool, and the unit tests call the
  write tools positionally: add new arguments before it, never after, or the tests hand the context to your argument.
- Guardrails are code: `callbacks.mask_pii_before_model`, `enforce_store_scope_before_tool`, `enforce_role_before_tool`,
  `hand_back_after_model` (a task agent always hands back), `enforce_dataset_allowlist_before_tool`,
  `plugins.LoopGuardPlugin` (30 model calls and 3 identical tool calls per request), `tools/sql_guard.assert_select_only`, `plugins.IngressRedactionPlugin`.
- Data access goes through `tools/data_backend.make_backend()` (BigQuery; `FakeBackend` in tests).

After any change: `uv run pytest tests/unit tests/quickstarts -q`, the seven golden prompts in `uv run adk web agents --port 8000`, `uv run pytest tests/eval -q -k test_golden_gate_passes`. When a prompt change legitimately changes the shape of an
answer (shorter, an offer instead of a recital), update that case's reference in `eval/build_eval_set.py` and rebuild
the evalsets in the same commit: a stale reference leaves the judge on its threshold and the gate flips on correct answers.
Skills: google-adk, cymbal-beauty-domain.
