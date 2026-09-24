# Cymbal Beauty synthetic schema (generated)

Written by `skills/cymbal-beauty-domain/scripts/gen_schema_md.py` from `data/schemas/*.json` and
`data/fixtures.py`. Do not edit by hand; rerun the script after changing a schema.

- `DATA_VERSION`: `2026.09.21-ops2`
- Frozen clock (`FIXTURE_NOW_ISO`): `2026-10-03T09:00:00-05:00` (America/Chicago, a Saturday); coaching week `2026-W39`
- Brands (all fictional): Lumière Skin, Velvet Root, Aurelia Cosmetics, Brightside Naturals, Meridian Fragrance, Tidewater Botanicals, Noor Beauty, Cymbal Collection

## Where each table lives

| Table | BigQuery dataset | Rows | Mutable |
|---|---|---:|---|
| `products` | `<project>.cymbal_beauty_<namespace>_<env>` | 600 | no |
| `reviews` | `<project>.cymbal_beauty_<namespace>_<env>` | 6000 | no |
| `stores` | `<project>.cymbal_beauty_<namespace>_<env>` | 40 | no |
| `store_inventory` | `<project>.cymbal_beauty_<namespace>_<env>` | 24000 | no |
| `associates` | `<project>.cymbal_beauty_<namespace>_<env>` | 200 | no |
| `store_tasks` | `<project>.cymbal_beauty_<namespace>_<env>` | 400 | yes |
| `bopis_orders` | `<project>.cymbal_beauty_<namespace>_<env>` | 2000 | no |
| `store_traffic` | `<project>.cymbal_beauty_<namespace>_<env>` | 6720 | no |
| `shrink_events` | `<project>.cymbal_beauty_<namespace>_<env>` | 1500 | no |
| `guest_feedback` | `<project>.cymbal_beauty_<namespace>_<env>` | 800 | no |
| `coaching_signals` | `<project>.cymbal_beauty_<namespace>_<env>` | 624 | no |
| `replenishment` | `<project>.cymbal_beauty_<namespace>_<env>` | 1200 | no |
| `operations_context` | `<project>.cymbal_beauty_<namespace>_<env>` | 16 | no |
| `pos_daily_product_sales` | `<project>.cymbal_beauty_<namespace>_<env>` | 40 | no |
| `worked_shifts` | `<project>.cymbal_beauty_<namespace>_<env>` | 16 | no |

`<env>` is `dev`, `preprod` or `prod` (`STORE_OPS_ENV`). One dataset per environment. `store_tasks` is the only
table the agent writes to (`create_store_task`, `delegate_task`, both idempotent on a key kept in session state);
`bash data/load.sh --env dev --tables store_tasks` reloads it. Every other table is read-only for the agent.

## Named fixtures (guaranteed by data/generate.py)

| Fixture | Value |
|---|---|
| Hero store | `S-014` Cymbal Beauty Naperville (Naperville, IL) |
| Store manager | `U-M014` Dana, role store_manager, store S-014 |
| Associate | `A-1004` Priya, skills bopis, skincare, shift 09:00-13:00 local, current_task NULL |
| District manager | `A-1001`, role district_manager, home store S-014 |
| Hero product | `P-0101` Lumière Hydra Cream (brand Lumière Skin, moisturizer, price 28.0, fragrance-free, skin_types `dry,sensitive`) |
| OSA exception | `P-0101` at `S-014`: on_hand 7, on_shelf_qty 0, backroom_qty 7, reorder_point 12, shelf_capacity 18; replenishment delayed, nothing in transit; no open task |
| BOPIS backlog | 9 pending orders at `S-014` promised by 11:00 local, 3 of them for `P-0101` |
| Traffic | `S-014` today: 09:00 = 40 visitors, 10:00-12:00 = 72 / 88 / 80 (the peak) |
| Shrink pattern | `P-0420` Noir Velvet Eau de Parfum (fragrance, locked_case true, price 95.0): 6 events at `S-014` in the last 14 days |
| Guest feedback | two `S-014` rows in the last 7 days with rating <= 2 and topic checkout_wait |
| Coaching signal | `A-1007` bopis_pick_rate 0.52 for `2026-W39` |

## Tables

### `products`

| Column | BigQuery type | Mode | Description |
|---|---|---|---|
| `product_id` | STRING | REQUIRED | Catalog id, e.g. P-0101 |
| `brand` | STRING | REQUIRED | Fictional brand |
| `name` | STRING | REQUIRED |  |
| `category` | STRING | REQUIRED | skincare\|haircare\|bath\|fragrance\|makeup |
| `subcategory` | STRING | REQUIRED |  |
| `price_usd` | FLOAT64 | REQUIRED |  |
| `is_fragrance_free` | BOOL | REQUIRED |  |
| `is_clean` | BOOL | REQUIRED | Clean-beauty flag |
| `locked_case` | BOOL | REQUIRED | Kept in a locked fixture (high-value fragrance) |
| `skin_types` | STRING | NULLABLE | Comma-separated: dry,oily,combination,sensitive,normal |
| `hair_types` | STRING | NULLABLE | Comma-separated: straight,wavy,curly,coily |
| `key_ingredients` | STRING | NULLABLE | Comma-separated |
| `description` | STRING | NULLABLE |  |
| `rating_avg` | FLOAT64 | NULLABLE |  |
| `rating_count` | INT64 | NULLABLE |  |

### `reviews`

| Column | BigQuery type | Mode | Description |
|---|---|---|---|
| `review_id` | STRING | REQUIRED |  |
| `product_id` | STRING | REQUIRED |  |
| `rating` | INT64 | REQUIRED | 1-5 |
| `title` | STRING | NULLABLE |  |
| `body` | STRING | NULLABLE |  |
| `skin_type` | STRING | NULLABLE |  |
| `created_at` | TIMESTAMP | REQUIRED |  |

### `stores`

| Column | BigQuery type | Mode | Description |
|---|---|---|---|
| `store_id` | STRING | REQUIRED | e.g. S-014 |
| `name` | STRING | REQUIRED |  |
| `city` | STRING | REQUIRED |  |
| `state` | STRING | REQUIRED |  |
| `zip` | STRING | NULLABLE |  |
| `has_salon` | BOOL | REQUIRED |  |
| `has_brow_bar` | BOOL | REQUIRED |  |
| `opens` | STRING | REQUIRED | HH:MM local |
| `closes` | STRING | REQUIRED |  |
| `lat` | FLOAT64 | NULLABLE |  |
| `lng` | FLOAT64 | NULLABLE |  |

### `store_inventory`

| Column | BigQuery type | Mode | Description |
|---|---|---|---|
| `store_id` | STRING | REQUIRED |  |
| `product_id` | STRING | REQUIRED |  |
| `on_hand` | INT64 | REQUIRED | System count = on_shelf_qty + backroom_qty |
| `on_shelf_qty` | INT64 | REQUIRED | Units on the sales floor |
| `backroom_qty` | INT64 | REQUIRED | Units in the backroom |
| `reorder_point` | INT64 | REQUIRED | Replenish when on_hand falls below this |
| `shelf_capacity` | INT64 | REQUIRED | Planogram facings x depth |
| `bopis_eligible` | BOOL | REQUIRED | Buy online, pick up in store |
| `updated_at` | TIMESTAMP | REQUIRED |  |

### `associates`

| Column | BigQuery type | Mode | Description |
|---|---|---|---|
| `associate_id` | STRING | REQUIRED | A-1004 (associates and district managers) or U-M014 (store managers) |
| `store_id` | STRING | REQUIRED | Home store |
| `first_name` | STRING | REQUIRED |  |
| `role` | STRING | REQUIRED | associate\|store_manager\|district_manager |
| `skills` | STRING | REPEATED | Subset of bopis,skincare,fragrance,makeup,haircare,cash_wrap,backroom |
| `shift_start` | TIMESTAMP | REQUIRED | Today's shift |
| `shift_end` | TIMESTAMP | REQUIRED |  |
| `current_task` | STRING | NULLABLE | What the associate is doing right now; NULL = free |

### `store_tasks`

| Column | BigQuery type | Mode | Description |
|---|---|---|---|
| `task_id` | STRING | REQUIRED | T-00042 (generated) or T-<8 hex> (created by the agent) |
| `store_id` | STRING | REQUIRED |  |
| `task_type` | STRING | REQUIRED | backroom_check\|replenish\|cycle_count\|coverage_move\|investigation\|coaching\|planogram_fix\|signage_fix |
| `product_id` | STRING | NULLABLE |  |
| `assignee_id` | STRING | NULLABLE |  |
| `status` | STRING | REQUIRED | open\|done\|cancelled |
| `source` | STRING | REQUIRED | agent\|manager\|system |
| `created_at` | TIMESTAMP | REQUIRED |  |
| `due_at` | TIMESTAMP | REQUIRED |  |
| `note` | STRING | NULLABLE |  |
| `task_key` | STRING | NULLABLE | Idempotency key of the create call: a hash of store, type, product, assignee and note |
| `delegation_key` | STRING | NULLABLE | Idempotency key of the last delegate call |

### `bopis_orders`

| Column | BigQuery type | Mode | Description |
|---|---|---|---|
| `order_id` | STRING | REQUIRED |  |
| `store_id` | STRING | REQUIRED |  |
| `product_id` | STRING | REQUIRED |  |
| `qty` | INT64 | REQUIRED |  |
| `promised_at` | TIMESTAMP | REQUIRED | Pick-up time promised to the guest |
| `status` | STRING | REQUIRED | pending\|picked\|ready\|collected |

### `store_traffic`

| Column | BigQuery type | Mode | Description |
|---|---|---|---|
| `store_id` | STRING | REQUIRED |  |
| `ts_hour` | TIMESTAMP | REQUIRED | Start of the hour; 12 buckets a day, 09:00-20:00 local; today's rows are expected traffic |
| `visitors` | INT64 | REQUIRED |  |
| `transactions` | INT64 | REQUIRED |  |
| `sales_usd` | FLOAT64 | REQUIRED |  |

### `shrink_events`

| Column | BigQuery type | Mode | Description |
|---|---|---|---|
| `event_id` | STRING | REQUIRED |  |
| `store_id` | STRING | REQUIRED |  |
| `product_id` | STRING | REQUIRED |  |
| `event_type` | STRING | REQUIRED | damage\|unknown_loss\|return_anomaly\|adjustment |
| `qty` | INT64 | REQUIRED |  |
| `value_usd` | FLOAT64 | REQUIRED |  |
| `event_ts` | TIMESTAMP | REQUIRED |  |

### `guest_feedback`

| Column | BigQuery type | Mode | Description |
|---|---|---|---|
| `feedback_id` | STRING | REQUIRED |  |
| `store_id` | STRING | REQUIRED |  |
| `submitted_at` | TIMESTAMP | REQUIRED |  |
| `rating` | INT64 | REQUIRED | 1-5 |
| `topic` | STRING | REQUIRED | checkout_wait\|associate_help\|stock\|store_condition\|salon |
| `comment` | STRING | NULLABLE | Synthetic text, no PII |

### `coaching_signals`

| Column | BigQuery type | Mode | Description |
|---|---|---|---|
| `associate_id` | STRING | REQUIRED |  |
| `period` | STRING | REQUIRED | ISO week, e.g. 2026-W39 |
| `metric` | STRING | REQUIRED | bopis_pick_rate\|cycle_count_accuracy\|guest_rating\|task_completion |
| `value` | FLOAT64 | REQUIRED |  |

### `replenishment`

| Column | BigQuery type | Mode | Description |
|---|---|---|---|
| `store_id` | STRING | REQUIRED |  |
| `product_id` | STRING | REQUIRED |  |
| `expected_at` | TIMESTAMP | REQUIRED |  |
| `qty` | INT64 | REQUIRED |  |
| `status` | STRING | REQUIRED | scheduled\|in_transit\|received\|delayed |

### `operations_context`

| Column | BigQuery type | Mode | Description |
|---|---|---|---|
| `store_id` | STRING | REQUIRED |  |
| `system` | STRING | REQUIRED |  |
| `subject_id` | STRING | REQUIRED |  |
| `captured_at` | TIMESTAMP | REQUIRED |  |
| `source` | STRING | REQUIRED |  |
| `payload` | STRING | REQUIRED |  |

### `pos_daily_product_sales`

| Column | BigQuery type | Mode | Description |
|---|---|---|---|
| `store_id` | STRING | REQUIRED |  |
| `business_date` | DATE | REQUIRED |  |
| `product_id` | STRING | REQUIRED |  |
| `units_sold` | INT64 | REQUIRED |  |
| `gross_sales_cents` | INT64 | REQUIRED |  |
| `discount_cents` | INT64 | REQUIRED |  |
| `net_sales_cents` | INT64 | REQUIRED |  |

### `worked_shifts`

| Column | BigQuery type | Mode | Description |
|---|---|---|---|
| `store_id` | STRING | REQUIRED |  |
| `business_date` | DATE | REQUIRED |  |
| `associate_id` | STRING | REQUIRED |  |
| `clock_in` | TIMESTAMP | REQUIRED |  |
| `clock_out` | TIMESTAMP | REQUIRED |  |
| `unpaid_break_minutes` | INT64 | REQUIRED |  |
| `paid_minutes` | INT64 | REQUIRED |  |

## Value conventions

- Ids: products `P-0001`..`P-0600`, stores `S-001`..`S-040`, store managers `U-M001`..`U-M040`, associates and
  district managers `A-1000`..`A-1159`, tasks `T-00001`.. (agent-created: `T-<8 hex>`), orders `BO-000001`..,
  shrink events `SE-00001`.., feedback `GF-00001`.., reviews `R-00001`..
- `products.category` by id range: skincare (P-0001..0180), haircare (..0300), bath (..0380), fragrance (..0450), makeup (..0600).
- Multi-valued text columns are comma-separated strings (`skin_types`, `hair_types`, `key_ingredients`),
  so filter with `LIKE '%sensitive%'`; `associates.skills` is a real ARRAY<STRING> (`'bopis' IN UNNEST(skills)`).
- `store_inventory.on_hand = on_shelf_qty + backroom_qty` on every row. An OSA exception is `on_shelf_qty = 0 AND on_hand > 0`
  or `on_hand < reorder_point`.
- Timestamps are stored in UTC; the frozen clock is 09:00 America/Chicago = 14:00 UTC. Shifts, BOPIS promises and
  today's traffic all sit on the frozen day; `store_traffic` covers 14 days x 12 hours (09:00-20:00 local).
- History tables (`store_tasks`, `guest_feedback`) cover the last 14 days; `shrink_events` the last 28.
- `guest_feedback.comment` is synthetic text with no names, emails or phone numbers.
