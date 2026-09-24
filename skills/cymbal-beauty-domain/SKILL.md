---
name: cymbal-beauty-domain
description: The Cymbal Beauty synthetic store-operations domain used by this workshop (the thirteen tables, columns, named fixtures, golden prompts, expected tool trajectories, BigQuery SQL). Use when writing SQL, tools, tests, evalsets or prompts against cymbal_beauty_<namespace>_<env>, when you need the hero fixtures (Dana the Naperville manager, Priya, Lumière Hydra Cream, the P-0420 shrink pattern) or when checking a business invariant. Not for ADK API questions (see google-adk) or for loading data into BigQuery (see gcp-integration).
metadata:
  workshop: cymbal-beauty-adk-workshop
  version: "2.0"
  verified: "2026-09-18"
allowed-tools: Bash Read
---

# Cymbal Beauty domain

Cymbal Beauty is a fictional beauty retailer with 40 stores and a 600-product catalog from eight fictional
brands. The running example is the **agentic store manager**: a store manager's start-of-day assistant over
inventory, BOPIS (buy online, pick up in store) orders, staffing, shrink and store tasks. Everything is
synthetic (`data/generate.py`, `random.seed(42)`, frozen clock) so every attendee's namespace has the same rows.

## When to use

- Writing or reviewing SQL against `cymbal_beauty_<namespace>_<env>` in BigQuery.
- Adding a tool, prompt, unit test or eval case that must reference real ids, names or quantities.
- Checking a golden prompt's expected trajectory or a business invariant before changing an agent.
- Explaining the running example's data flow to an attendee.

## Facts that override older docs

- The schema of record is `data/schemas/*.json`; the human-readable copy is
  [references/schema.md](references/schema.md), **generated** by
  `scripts/gen_schema_md.py`. Never edit it by hand; `scripts/check_skills.py` fails when it is stale.
- Named fixtures come from `agents/cymbal_store_ops/fixtures.py` (`data/fixtures.py` is a shim that imports it)
  and are constants, not conventions:
  - store `S-014` Cymbal Beauty Naperville; manager Dana `U-M014` (`store_manager`); associate Priya `A-1004`
    (skills `bopis`, `skincare`, on shift 09:00–13:00, no current task); district manager Elena `A-1001` (home store
    S-014); associate Noor `A-1007` with the coaching signal (BOPIS pick rate 0.52 in week `2026-W39`).
  - product `P-0101` Lumière Hydra Cream at S-014: on_hand 7 = on_shelf 0 + backroom 7, reorder point 12, shelf
    capacity 18: the hero OSA (on-shelf availability) exception, recommendation `backroom_check`.
  - 9 BOPIS orders pending at S-014, promised by 11:00 on the frozen day; 3 of them for P-0101.
  - product `P-0420` Noir Velvet Eau de Parfum (fragrance, locked case): 6 shrink events at S-014 in 14 days.
  - no open task for P-0101 in the fixtures; a confirmed task action creates one, `bash data/load.sh --env dev --tables store_tasks` removes it.
- Frozen clock: `2026-10-03T09:00:00-05:00` (America/Chicago), a Saturday. "This morning", "until 11" and
  "by close" resolve against that clock (`workshop_clock` tool, `FIXTURE_NOW_ISO`).
- Thirteen tables, row counts asserted by the loader and by `uv run python scripts/check_env.py --stage ready`: products 600, reviews 6000, stores 40,
  store_inventory 24000, associates 200, store_tasks 400, bopis_orders 2000, store_traffic 6720,
  shrink_events 1500, guest_feedback 800, coaching_signals 624, replenishment 1200, operations_context 16.
- One dataset per attendee and environment: `cymbal_beauty_<namespace>_<env>` (`WORKSHOP_NAMESPACE` from
  `.env`; `env` is `dev`, `preprod` or `prod`). There is no separate members dataset any more.
- Identity comes from session state, never from the prompt: `identify_demo_user` (the workshop's stand-in for
  device sign-in) seeds `user:user_id`, `user:store_id`, `user:role` (`associate` | `store_manager` |
  `district_manager`) and `user:first_name`. `enforce_store_scope_before_tool` refuses another store or a city
  unless the role is `district_manager`; `enforce_role_before_tool` keeps coaching signals and the write tools to
  managers.
- The store-ops write path is `store_tasks`: manager creation/delegation uses `create_store_task` and `delegate_task`, with manager-role
  checks, `request_confirmation`, a deterministic `task_key` (a hash of the write, stored with the row, so a
  retried approval returns the original task) and a budget of two writes per request. Raw SQL is read-only:
  `execute_sql` runs with `WriteMode.BLOCKED` and the SQL guard excludes the people-data tables (`associates`,
  `coaching_signals`, `operations_context`), which are reachable only through the domain tools.
- Associates can also confirm completion or blocker updates for their own assigned tasks through
  `complete_my_task` and `report_my_task_blocker`; store, ownership and idempotency are checked in code.
  Development reads support managers reviewing the team and associates reviewing themselves.
- The fault values are `none`, `stale_stock` and `stale_backlog` (`STORE_OPS_FAULT`; `VALID_FAULTS` in
  `agents/cymbal_store_ops/config.py`); read their implementations in `agents/cymbal_store_ops/tools/domain_tools.py`
  before asserting what a fault changes. `stale_stock` trips `stock_invariant`; `stale_backlog` trips
  `plan_invariant` or `coverage_invariant`.
- Multi-valued columns: `products.skin_types`, `hair_types`, `key_ingredients` are comma-separated strings;
  `associates.skills` is a `REPEATED` column (use `UNNEST`).
- `DATA_VERSION` (`2026.09.21-ops2`) is a dataset label and part of the release manifest; bump it in
  `agents/cymbal_store_ops/fixtures.py` when the generator changes.

## Repo map

| Path | What it is |
|---|---|
| `agents/cymbal_store_ops/fixtures.py` | Frozen constants: hero ids, roles, task types, expected row counts, `DATA_VERSION` |
| `data/generate.py` | Deterministic generator, stdlib only, writes `data/out/*.ndjson` |
| `data/schemas/*.json` | BigQuery table schemas |
| `data/load.sh` | Loader with row-count assertions (`uv run python data/generate.py && bash data/load.sh --env dev`; `--tables store_tasks` is what `bash data/load.sh --env dev --tables store_tasks` runs) |
| `agents/cymbal_store_ops/tools/` | Domain tools over `DataBackend` (`data_backend.py`, `backends/bigquery.py`, `backends/fake.py`, `sql_guard.py`) |
| `agents/cymbal_store_ops/callbacks.py` | The guardrails in code: PII mask, dataset allow-list, store scope, role gate, hand-back |
| `eval/build_eval_set.py` | `CASES`: the goldens of record (`manager_identity`, `daily_plan_fanout`, `osa_explanation`, `coverage_recommendation`, `task_approval_hitl`, `hr_refusal`, `blocked_write_refusal`, `off_topic_guardrail`); `GATE_EXCLUDED` keeps the HITL case out of the gate |
| `eval/metrics.py` | `data_tool_trajectory`, `stock_invariant`, `plan_invariant`, `coverage_invariant`, `refusal_invariant` |
| `eval/evalsets/` | `golden.evalset.json` (all cases), `gate.evalset.json` (the gate), the fault evalsets; regenerate with `eval/build_eval_set.py` |
| `tests/unit/` | Tests that use `FakeBackend` and the fixtures, no cloud |
| `references/schema.md` | Generated column-level schema |
| `references/golden-prompts.md` | Prompts, expected trajectories, invariants, SQL examples |

## Recipes

### Regenerate the schema reference after a schema change

```bash
uv run python skills/cymbal-beauty-domain/scripts/gen_schema_md.py
uv run python skills/cymbal-beauty-domain/scripts/gen_schema_md.py --check   # what the lint runs
```

### Use fixtures in a test instead of literals

```python
import sys; sys.path.insert(0, "data")
import fixtures as F

def test_hero_stock(fake_backend):
    result = fake_backend.check_store_stock(product_name=F.HERO_PRODUCT_NAME, store_id=F.HERO_STORE_ID)
    row = result["rows"][0]          # every backend call returns an envelope: status and rows (or an error)
    assert row["on_hand"] == F.HERO_STORE_ON_HAND and row["on_shelf_qty"] == F.HERO_STORE_ON_SHELF
```

`fake_backend` is the fixture in `tests/conftest.py`; the tool tests in `tests/unit/test_domain_tools.py` show
how to seed `user:` state with `FakeToolContext` before calling a tool.

### Parameterised stock lookup (BigQuery)

```sql
SELECT s.store_id, s.name, i.on_hand, i.on_shelf_qty, i.backroom_qty, i.reorder_point, i.bopis_eligible
FROM `{project}.cymbal_beauty_{namespace}_{env}.store_inventory` i
JOIN `{project}.cymbal_beauty_{namespace}_{env}.stores` s USING (store_id)
JOIN `{project}.cymbal_beauty_{namespace}_{env}.products` p USING (product_id)
WHERE p.name = @product_name AND s.store_id = @store_id
```

More examples in [references/golden-prompts.md](references/golden-prompts.md).

### Add an eval case for a new prompt

1. Pick the invariant (id, count, quantity, associate, refusal) rather than exact wording; put a deterministic
   assertion in `eval/metrics.py` when a number must be right every time.
2. Record the expected tool names in order; for `execute_sql` never assert the SQL text
   (the custom `data_tool_trajectory` metric compares names only for the SQL tools).
3. Add the case to `CASES` in `eval/build_eval_set.py`, run `uv run python eval/build_eval_set.py`, then
   `uv run pytest tests/eval -q -k test_golden_gate_passes`. Cases in `GATE_EXCLUDED` land only in `golden.evalset.json`.

## Gotchas

- `products.name` is not unique across brands in general; the hero product is unique by construction.
  Filter by `product_id` once you have it (`_resolve_product` in `domain_tools.py` does this for the tools).
- `store_inventory.on_hand` is always `on_shelf_qty + backroom_qty`; `updated_at` is before the frozen clock,
  so "fresh" means relative to that clock, not to today.
- `stores.has_salon` exists (30 of 40 stores) and `guest_feedback.topic` has a `salon` value, but there are no
  salon or member tables: the assistant does not book anything.
- Ratings live on `products.rating_avg`/`rating_count` (derived from `reviews`); do not recompute them
  in prompts unless the question is about a time window.
- `store_tasks` is the one mutable table: a confirmed task action adds an open task for P-0101, which fails the
  `uv run python scripts/check_env.py --stage ready` fixture row and the sequential pattern script. Run `bash data/load.sh --env dev --tables store_tasks` before evals.
- Managers talk in first names; `_resolve_assignee` turns a first name or id into an associate at the signed-in
  store and returns `not_found`, `ambiguous` or `invalid_assignee` (a district manager) errors instead of guessing.
- The PII callback masks emails and phone numbers in model input; the synthetic data carries no personal contact
  details.

## References

- [references/schema.md](references/schema.md), generated column reference
- [references/golden-prompts.md](references/golden-prompts.md), prompts to trajectories, invariants, SQL
- `agents/cymbal_store_ops/fixtures.py`, `data/generate.py`, `data/schemas/`
- BigQuery query syntax: https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/query-syntax
- BigQuery parameterized queries: https://docs.cloud.google.com/bigquery/docs/parameterized-queries

The operations extension adds dated fulfillment activity, stock locations, workforce constraints, merchandising
directives, loss controls and learning snapshots. Associates can read their own development and complete their
own assigned task through scoped domain tools. Manager-only legacy coaching reads remain restricted.

## Expanded operational context

Sixteen source snapshots supply stock locations, explicit reservations/count observations, coverage constraints, merchandising directives, loss controls/reconciliation, dated pick activity and learning. `get_inventory_context` computes allocation from gross stock, subtracting reservations once. Associates can read their own development and use confirmed, ownership-checked task completion/blocker reporting; these writes do not alter inventory or order readiness.
