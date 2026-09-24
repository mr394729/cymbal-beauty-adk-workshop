# Data requirements: what an example dataset needs

This page answers "what data would an example dataset need?" for each store operations use case: the tables and
the minimum columns the agents actually read (the SQL in `agents/cymbal_store_ops/tools/backends/bigquery.py`),
the grain, how fresh each input has to be, and one example value per column from the synthetic set
(`data/generate.py`; the named fixtures are in `agents/cymbal_store_ops/fixtures.py`). Column types are in
`data/schemas/*.json`; `uv run python data/generate.py && bash data/load.sh --env dev` loads the synthetic version.

Conventions that hold for every table:

- Timestamps are `TIMESTAMP` in UTC. The tools return them in store-local time: `2026-10-03 14:30 UTC` reads as
  09:30 in Naperville.
- Ids are prefixed strings: stores `S-014`, products `P-0101`, associates `A-1004` (store managers `U-M014`), tasks
  `T-00137`, pick-up orders `BO-000651`.
- Every read is filtered by `store_id`, and the store comes from the signed-in identity, never from the
  conversation.
- Store-scoped time windows are anchored at the workshop clock, Saturday 2026-10-03 09:00 in Naperville.

## At a glance

R = read, W = written by the approve or delegate step (always behind a confirmation).

| Table | Grain | Briefing | Orchestration | Inventory | Loss and damage | Development | Promo proof |
|---|---|---|---|---|---|---|---|
| `stores` | one row per store | R | R | R | R | R | |
| `associates` | one row per associate, with today's shift | R | R | R | R | R | |
| `products` | one row per product | R | | R | R | | |
| `store_inventory` | store x product, current position | R | | R | | | |
| `replenishment` | one inbound delivery line | R | | R | | | |
| `bopis_orders` | one pick-up order line | R | R | R | | | |
| `store_traffic` | store x hour | R | R | | R | | |
| `store_tasks` | one task | R, W | R, W | R, W | R, W | W | |
| `shrink_events` | one loss or damage event | R | | | R | | |
| `guest_feedback` | one guest survey response | R | | | | | |
| `coaching_signals` | associate x ISO week x metric | | | | | R | |
| promotion plan (not in the 12 tables) | product x promotion week x store group | | | | | | R |

`reviews` (one row per product review) is not a use case input, but `get_product_details` joins it, and a task that
names a product reads the product through that call. With no reviews of your own, provide an empty `reviews` view
with the same columns.

## Every use case: who is signed in, which store, which product

| Table | Columns read, with a synthetic example | Freshness needed |
|---|---|---|
| `associates` | `associate_id` U-M014 · `first_name` Dana · `role` store_manager (or associate, district_manager) · `store_id` S-014 | on change; a role change must land before the person's next session |
| `stores` | `store_id` S-014 · `name` Cymbal Beauty Naperville · `city` Naperville · `state` IL · `opens` 09:00 · `closes` 21:00 | on change |
| `products` | `product_id` P-0101 · `name` Lumière Hydra Cream · `category` skincare · `price_usd` 28.00 · `locked_case` false (true for P-0420, Noir Velvet Eau de Parfum) | daily |

## Agentic store manager briefing

`daily_briefing` gathers three signal branches in parallel (inventory: `get_osa_exceptions`, `get_bopis_demand`;
coverage: `get_traffic_and_backlog`, `get_shift_roster`, `get_guest_feedback`; shrink: `get_shrink_signals`,
`get_task_history`), then `plan_writer` returns at most five prioritized items with suggested tasks. The plan is only
as current as its oldest input, so everything has to be in place by the morning huddle.

| Table | Columns read, with a synthetic example | Freshness needed |
|---|---|---|
| `store_inventory` | `on_hand` 7 · `on_shelf_qty` 0 · `backroom_qty` 7 · `reorder_point` 12 · `shelf_capacity` 18 · `bopis_eligible` true · `updated_at` 2026-10-03 12:00 UTC | under 1 hour old at huddle time |
| `replenishment` | `product_id` P-0101 · `expected_at` 2026-10-01 14:00 UTC · `qty` 12 · `status` delayed | daily |
| `bopis_orders` | `order_id` BO-000651 · `product_id` P-0101 · `qty` 1 · `promised_at` 2026-10-03 14:30 UTC · `status` pending | under 15 minutes |
| `store_traffic` | `ts_hour` 2026-10-03 14:00 UTC · `visitors` 40 · `transactions` 16 · `sales_usd` 800.71 (today's rows are the forecast) | today's forecast published before opening |
| `associates` | `skills` [bopis, skincare] · `shift_start` 2026-10-03 14:00 UTC · `shift_end` 2026-10-03 18:00 UTC · `current_task` NULL | today's schedule published before opening |
| `guest_feedback` | `feedback_id` GF-00261 · `submitted_at` 2026-10-01 10:00 UTC · `rating` 1 · `topic` checkout_wait · `comment` "Checkout line was out the door on Saturday morning." | daily (the last 7 days are read) |
| `shrink_events` | `product_id` P-0420 · `event_type` unknown_loss · `qty` 1 · `value_usd` 95.00 · `event_ts` 2026-10-02 11:00 UTC | daily (the last 14 days are read) |
| `store_tasks` | `task_id` T-00137 · `task_type` planogram_fix · `product_id` P-0233 · `assignee_id` A-1005 · `status` open · `source` system · `created_at` 2026-10-01 09:00 UTC · `due_at` 2026-10-03 09:00 UTC · `note` "Haircare endcap does not match the October planogram." | live: the agent reads and writes it |

What stale looks like: `STORE_OPS_FAULT=stale_backlog uv run pytest tests/eval -q -k test_golden_gate_passes` makes the pick-up sync three hours late, the briefing
sees no pending orders, and the plan misses the coverage gap.

## Associate orchestration and next best action

`get_traffic_and_backlog` sets rising traffic against the pick-up backlog; `get_shift_roster` returns who is on shift
and the coverage candidates (free associates with the needed skill, those covering the whole window first); the
manager approves a `coverage_move` task and delegates it.

| Table | Columns read, with a synthetic example | Freshness needed |
|---|---|---|
| `associates` | `associate_id` A-1004 · `first_name` Priya · `role` associate · `skills` [bopis, skincare] · `shift_start` 2026-10-03 14:00 UTC · `shift_end` 2026-10-03 18:00 UTC · `current_task` NULL (free) | schedule before opening; `current_task` under 15 minutes |
| `store_traffic` | `store_id` S-014 · `ts_hour` 2026-10-03 14:00 UTC · `visitors` 40 · `transactions` 16 · `sales_usd` 800.71 | an hourly forecast covering the next 4 to 12 hours |
| `bopis_orders` | `store_id` S-014 · `status` pending · `promised_at` 2026-10-03 14:30 UTC (9 pending at S-014 in the next 4 hours) | under 15 minutes |
| `store_tasks` | writes `task_type` coverage_move · `assignee_id` A-1004 · `status` open · `source` agent · `due_at` · `note` · `task_key`; delegation sets `assignee_id` and `delegation_key` | live |

## Inventory excellence

`get_osa_exceptions` and `check_store_stock` apply the on-shelf availability rule in code: backroom check when the
shelf is empty and the backroom is not, replenish below the reorder point with nothing in transit, cycle count when
the system count has no units behind it, escalate when it is an exception and none of those apply. `find_nearby_stock`, `get_bopis_demand`,
`get_replenishment_status` and `get_task_status` fill in the context.

| Table | Columns read, with a synthetic example | Freshness needed |
|---|---|---|
| `store_inventory` | `store_id` S-014 · `product_id` P-0101 · `on_hand` 7 (the system count) · `on_shelf_qty` 0 · `backroom_qty` 7 · `reorder_point` 12 · `shelf_capacity` 18 · `bopis_eligible` true · `updated_at` 2026-10-03 12:00 UTC | under 1 hour: the rule compares shelf with backroom, so a stale split changes the recommendation |
| `replenishment` | `product_id` P-0342 · `expected_at` 2026-10-10 19:00 UTC · `qty` 24 · `status` in_transit | daily at least; an `in_transit` line is what stops a duplicate replenish |
| `bopis_orders` | `product_id` P-0101 · `qty` 1 · `promised_at` 2026-10-03 14:30 UTC · `status` pending (3 pending for P-0101) | under 15 minutes |
| `store_tasks` | `task_id` T-00138 · `task_type` cycle_count · `product_id` P-0301 · `status` open · `due_at` 2026-10-03 11:00 UTC | live: open tasks keep the same work from being raised twice |
| `stores` | `state` IL (nearby stock is searched in the same state) | on change |

What stale looks like: `STORE_OPS_FAULT=stale_stock uv run pytest tests/eval -q -k test_golden_gate_passes` reports five phantom backroom units for P-0101; on hand
then reaches the reorder point, and `replenish` drops out of the recommended actions.

## Loss and damage prevention

`get_shrink_signals` groups events by product and type and recommends `investigate` at 5 or more events or $250 or
more in the window, otherwise `monitor`; `get_sales_pattern` shows whether shrink coincides with a sales change;
`get_task_history` shows what has already been tried. Quickstart 03 (damage report form) produces the record a
production app would add to `shrink_events`: store, product, quantity and event type, plus where in the store and a
one-sentence note.

| Table | Columns read, with a synthetic example | Freshness needed |
|---|---|---|
| `shrink_events` | `store_id` S-014 · `product_id` P-0420 · `event_type` unknown_loss (or damage, return_anomaly, adjustment) · `qty` 1 · `value_usd` 95.00 · `event_ts` 2026-10-02 11:00 UTC (6 events and $665.00 for P-0420 in 14 days) | daily; the next day is enough for a 14-day window |
| `products` | `category` fragrance · `locked_case` true · `price_usd` 95.00 | daily |
| `store_traffic` | daily totals by store-local day of `visitors`, `transactions`, `sales_usd` | daily |
| `store_tasks` | `task_type` investigation · `status` done · `created_at` 2026-09-23 08:00 UTC · `note` "Locked-case audit after two unknown-loss events; no cause found." | daily for history; live for new tasks |

No loss-prevention row names a person. If your source records who reported or handled an event, leave that column
out of the view.

## Associate development

`get_coaching_signals` returns one associate's weekly signals, for store managers and district managers only, and a
store manager only sees associates of their own store. It supports coaching conversations, never HR or
disciplinary decisions.

| Table | Columns read, with a synthetic example | Freshness needed |
|---|---|---|
| `coaching_signals` | `associate_id` A-1007 · `period` 2026-W39 · `metric` bopis_pick_rate (or cycle_count_accuracy, guest_rating, task_completion) · `value` 0.52 | weekly, once the ISO week has closed |
| `associates` | `first_name` · `role` · `store_id` S-014 · `skills` | on change |

## Promotion proof checking (quickstart 07)

The model reads a store's signage proof (PDF or image) into structured lines; `compare_promo_proof`, plain code,
compares them with the week's promotion plan. The plan is a file in the quickstart (`promo_plan_2026W40.json`) and a
promotions table in production; it is not one of the 12 workshop tables.

| Input | Fields, with a synthetic example | Freshness needed |
|---|---|---|
| promotion plan, product x week x store group | `week` 2026-W40 · `store_id` S-014 · `store_group` Chicagoland · `product_id` P-0101 · `product_name` Lumière Hydra Cream · `promo_price_usd` 22.99 · `start_date` 2026-10-04 · `end_date` 2026-10-10 | the approved plan, before proofs are checked for that week |
| signage proof, one document per store and week | numbered lines: `line` 1 · `product_id` P-0101 · `product_name` Lumière Hydra Cream · `sign_type` shelf talker · `promo_price_usd` 24.99 (the planted mismatch) · `start_date` 2026-10-04 · `end_date` 2026-10-10 | as uploaded |

## Bring your own data

Pointing the agents at real data means BigQuery views with these table and column names, inside a namespaced dataset.

1. **Same dataset, same names.** The backend reads `<project>.cymbal_beauty_<namespace>_<env>.<table>`. Create one
   view per table in that dataset, selecting from your source with the column names and types in
   `data/schemas/*.json` (`INT64`, `BOOL`, UTC `TIMESTAMP`, `skills` as a repeated `STRING`).
2. **`store_tasks` stays a table.** The agent inserts and updates it, and a view cannot take DML. Either keep it as a
   table the runtime identity may edit (and sync it to your task system), or implement `create_store_task` and
   `delegate_task` against that system in a backend.
3. **The agent reads views, never the source.** Authorize the view dataset on the source dataset and grant the runtime
   identity `roles/bigquery.dataViewer` on the view dataset only (`roles/bigquery.dataEditor` on `store_tasks`).
4. **Two workshop settings are code, not data.** The clock is frozen at `FIXTURE_NOW_ISO` in
   `agents/cymbal_store_ops/fixtures.py`, and one time zone (America/Chicago) serves every store. Real data needs the
   current time and each store's own zone.
5. **Keep the id shapes, or change their validators.** The MCP server accepts store ids like `S-014` (`STORE_ID` in
   `quickstarts/08-mcp-tools-agent/cymbal_mcp_server.py`); quickstart 03 accepts product ids like `P-0101`.
6. **The synthetic checks do not apply.** `data/load.sh` and `uv run python scripts/check_env.py --stage ready` assert the synthetic row counts and named
   fixtures; on real data they report a difference by design.

A worked example, `store_inventory` over a hypothetical source that keeps periodic position snapshots and a planogram
table (the `source-project` names are placeholders for yours). One row per store and product, the latest snapshot:

```sql
CREATE OR REPLACE VIEW `<project>.cymbal_beauty_<namespace>_dev.store_inventory` AS
SELECT
  FORMAT('S-%03d', pos.store_number)             AS store_id,
  CONCAT('P-', pos.sku)                          AS product_id,
  CAST(pos.perpetual_on_hand AS INT64)           AS on_hand,        -- the system count
  CAST(pos.sales_floor_units AS INT64)           AS on_shelf_qty,
  CAST(pos.stockroom_units AS INT64)             AS backroom_qty,
  CAST(pos.min_presentation_qty AS INT64)        AS reorder_point,
  CAST(pog.facings * pog.depth AS INT64)         AS shelf_capacity,
  pos.pickup_eligible                            AS bopis_eligible,
  pos.snapshot_ts                                AS updated_at      -- kept, so staleness stays visible
FROM `source-project.inventory.store_positions` AS pos
JOIN `source-project.merchandising.planogram_facings` AS pog USING (store_number, sku)
WHERE TRUE
QUALIFY ROW_NUMBER() OVER (PARTITION BY pos.store_number, pos.sku ORDER BY pos.snapshot_ts DESC) = 1;
```

Do not filter out old snapshots in the view: a missing row reads as "no stock", while an old `updated_at` can be seen
and questioned.

### What must never be in the views

| Rule | What it means for the views |
|---|---|
| No guest personal data | no guest names, emails, phone numbers, loyalty or member ids, addresses or payment details in any view. `bopis_orders` carries the order id, product, quantity, promised time and status only. Scrub names and contact details from `guest_feedback.comment` and review text before they reach the view: the agent redacts what people type, not what a tool returns. |
| Associates by id and first name only | `associate_id` and `first_name`, plus role, store, skills and today's shift. No surname, email, phone, address, pay, HR, disciplinary or medical fields. |
| Coaching signals for managers only | `coaching_signals` holds the four operational metrics per ISO week and nothing from HR files. The agents show it to store and district managers only (`enforce_role_before_tool`, plus the own-store check in `get_coaching_signals`). The runtime identity can read the table, so do not give an associate-facing app or a raw-SQL agent dataset-wide read on the dataset that holds it; grant those table-level access to the tables they need. |

## Further reading

- [CONNECTING_TO_DATA.md](CONNECTING_TO_DATA.md): the tool contract and the ways to expose a source.
- [IAM_MATRIX.md](IAM_MATRIX.md): the identities and grants per environment.
- Dataset and table access control: https://docs.cloud.google.com/bigquery/docs/access-control
