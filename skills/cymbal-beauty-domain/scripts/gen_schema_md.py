#!/usr/bin/env python3
"""Generate skills/cymbal-beauty-domain/references/schema.md from data/schemas/*.json.

    uv run python skills/cymbal-beauty-domain/scripts/gen_schema_md.py           # (re)write schema.md
    uv run python skills/cymbal-beauty-domain/scripts/gen_schema_md.py --check   # exit 1 if schema.md is stale
    uv run python skills/cymbal-beauty-domain/scripts/gen_schema_md.py --stdout  # print the generated text

The output is deterministic: same schemas + same fixtures -> byte-identical file. `scripts/check_skills.py`
runs `--stdout` and fails the lint when the committed file differs from the generated text.
Standard library only, so it runs before the project's virtualenv exists.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SCHEMAS = ROOT / "data" / "schemas"
FIXTURES = ROOT / "data" / "fixtures.py"
OUT = HERE.parent / "references" / "schema.md"

DATASET = "cymbal_beauty_<namespace>_<env>"
TABLE_ORDER = ["products", "reviews", "stores", "store_inventory", "associates", "store_tasks", "bopis_orders",
               "store_traffic", "shrink_events", "guest_feedback", "coaching_signals", "replenishment", "operations_context", "pos_daily_product_sales", "worked_shifts"]
MUTABLE = {"store_tasks"}

KNOWN_TYPES = {"STRING", "INT64", "FLOAT64", "BOOL", "TIMESTAMP", "DATE"}


def load_fixtures():
    spec = importlib.util.spec_from_file_location("fixtures", FIXTURES)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {FIXTURES}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_schemas() -> dict[str, list[dict]]:
    if not SCHEMAS.is_dir():
        raise SystemExit(f"schema directory missing: {SCHEMAS}")
    schemas = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(SCHEMAS.glob("*.json"))}
    missing = [t for t in TABLE_ORDER if t not in schemas]
    extra = [t for t in schemas if t not in TABLE_ORDER]
    if missing or extra:
        raise SystemExit(f"schema set changed: missing={missing} extra={extra} -> update TABLE_ORDER in {__file__}")
    return schemas


def render() -> str:
    F = load_fixtures()
    schemas = load_schemas()
    counts = {**F.EXPECTED_ROW_COUNTS, "pos_daily_product_sales": 40, "worked_shifts": 16}
    lines: list[str] = []
    w = lines.append
    w("# Cymbal Beauty synthetic schema (generated)")
    w("")
    w("Written by `skills/cymbal-beauty-domain/scripts/gen_schema_md.py` from `data/schemas/*.json` and")
    w("`data/fixtures.py`. Do not edit by hand; rerun the script after changing a schema.")
    w("")
    w(f"- `DATA_VERSION`: `{F.DATA_VERSION}`")
    w(f"- Frozen clock (`FIXTURE_NOW_ISO`): `{F.FIXTURE_NOW_ISO}` ({F.FIXTURE_TIMEZONE}, a Saturday); coaching week `{F.FIXTURE_WEEK}`")
    w(f"- Brands (all fictional): {', '.join(F.BRANDS)}")
    w("")
    w("## Where each table lives")
    w("")
    w("| Table | BigQuery dataset | Rows | Mutable |")
    w("|---|---|---:|---|")
    for t in TABLE_ORDER:
        w(f"| `{t}` | `<project>.{DATASET}` | {counts[t]} | {'yes' if t in MUTABLE else 'no'} |")
    w("")
    w("`<env>` is `dev`, `preprod` or `prod` (`STORE_OPS_ENV`). One dataset per environment. `store_tasks` is the only")
    w("table the agent writes to (`create_store_task`, `delegate_task`, both idempotent on a key kept in session state);")
    w("`bash data/load.sh --env dev --tables store_tasks` reloads it. Every other table is read-only for the agent.")
    w("")
    w("## Named fixtures (guaranteed by data/generate.py)")
    w("")
    w("| Fixture | Value |")
    w("|---|---|")
    w(f"| Hero store | `{F.HERO_STORE_ID}` {F.HERO_STORE_NAME} ({F.HERO_STORE_CITY}, IL) |")
    w(f"| Store manager | `{F.HERO_MANAGER_ID}` {F.HERO_MANAGER_FIRST_NAME}, role store_manager, store {F.HERO_STORE_ID} |")
    w(f"| Associate | `{F.HERO_ASSOCIATE_ID}` {F.HERO_ASSOCIATE_FIRST_NAME}, skills {', '.join(F.HERO_ASSOCIATE_SKILLS)}, shift 09:00-13:00 local, current_task NULL |")
    w(f"| District manager | `{F.HERO_DISTRICT_MANAGER_ID}`, role district_manager, home store {F.HERO_STORE_ID} |")
    w(f"| Hero product | `{F.HERO_PRODUCT_ID}` {F.HERO_PRODUCT_NAME} (brand Lumière Skin, moisturizer, price 28.0, fragrance-free, skin_types `dry,sensitive`) |")
    w(f"| OSA exception | `{F.HERO_PRODUCT_ID}` at `{F.HERO_STORE_ID}`: on_hand {F.HERO_STORE_ON_HAND}, on_shelf_qty {F.HERO_STORE_ON_SHELF}, backroom_qty {F.HERO_STORE_BACKROOM}, reorder_point {F.HERO_REORDER_POINT}, shelf_capacity {F.HERO_SHELF_CAPACITY}; replenishment delayed, nothing in transit; no open task |")
    w(f"| BOPIS backlog | {F.HERO_BOPIS_PENDING} pending orders at `{F.HERO_STORE_ID}` promised by 11:00 local, {F.HERO_BOPIS_PENDING_FOR_PRODUCT} of them for `{F.HERO_PRODUCT_ID}` |")
    w(f"| Traffic | `{F.HERO_STORE_ID}` today: 09:00 = 40 visitors, 10:00-12:00 = 72 / 88 / 80 (the peak) |")
    w(f"| Shrink pattern | `{F.SHRINK_PRODUCT_ID}` {F.SHRINK_PRODUCT_NAME} (fragrance, locked_case true, price 95.0): {F.SHRINK_EVENTS_14D} events at `{F.HERO_STORE_ID}` in the last 14 days |")
    w(f"| Guest feedback | two `{F.HERO_STORE_ID}` rows in the last 7 days with rating <= 2 and topic checkout_wait |")
    w(f"| Coaching signal | `{F.COACHING_ASSOCIATE_ID}` bopis_pick_rate {F.COACHING_LOW_PICK_RATE} for `{F.FIXTURE_WEEK}` |")
    w("")
    w("## Tables")
    w("")
    for t in TABLE_ORDER:
        w(f"### `{t}`")
        w("")
        w("| Column | BigQuery type | Mode | Description |")
        w("|---|---|---|---|")
        for col in schemas[t]:
            bq = col["type"]
            if bq not in KNOWN_TYPES:
                raise SystemExit(f"{t}.{col['name']}: unknown BigQuery type {bq} -> add it to KNOWN_TYPES")
            desc = (col.get("description") or "").replace("|", "\\|")
            w(f"| `{col['name']}` | {bq} | {col['mode']} | {desc} |")
        w("")
    w("## Value conventions")
    w("")
    w("- Ids: products `P-0001`..`P-0600`, stores `S-001`..`S-040`, store managers `U-M001`..`U-M040`, associates and")
    w("  district managers `A-1000`..`A-1159`, tasks `T-00001`.. (agent-created: `T-<8 hex>`), orders `BO-000001`..,")
    w("  shrink events `SE-00001`.., feedback `GF-00001`.., reviews `R-00001`..")
    w("- `products.category` by id range: skincare (P-0001..0180), haircare (..0300), bath (..0380), fragrance (..0450), makeup (..0600).")
    w("- Multi-valued text columns are comma-separated strings (`skin_types`, `hair_types`, `key_ingredients`),")
    w("  so filter with `LIKE '%sensitive%'`; `associates.skills` is a real ARRAY<STRING> (`'bopis' IN UNNEST(skills)`).")
    w("- `store_inventory.on_hand = on_shelf_qty + backroom_qty` on every row. An OSA exception is `on_shelf_qty = 0 AND on_hand > 0`")
    w("  or `on_hand < reorder_point`.")
    w("- Timestamps are stored in UTC; the frozen clock is 09:00 America/Chicago = 14:00 UTC. Shifts, BOPIS promises and")
    w("  today's traffic all sit on the frozen day; `store_traffic` covers 14 days x 12 hours (09:00-20:00 local).")
    w("- History tables (`store_tasks`, `guest_feedback`) cover the last 14 days; `shrink_events` the last 28.")
    w("- `guest_feedback.comment` is synthetic text with no names, emails or phone numbers.")
    w("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit 1 if the committed schema.md is stale")
    ap.add_argument("--stdout", action="store_true", help="print the generated text instead of writing it")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    text = render()
    out = Path(a.out)
    if a.stdout:
        sys.stdout.write(text)
        return 0
    if a.check:
        current = out.read_text(encoding="utf-8") if out.exists() else ""
        if current != text:
            print(f"STALE: {out} differs from the generated text; rerun {Path(__file__).name}", file=sys.stderr)
            return 1
        print(f"fresh: {out}")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({text.count(chr(10))} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
