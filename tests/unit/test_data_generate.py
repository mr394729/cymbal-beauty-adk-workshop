"""The generator is deterministic, every schema matches its table, and every named fixture holds."""
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import ROOT

sys.path.insert(0, str(ROOT / "data"))
import fixtures as F  # noqa: E402
import generate as G  # noqa: E402

NOW = datetime.fromisoformat(F.FIXTURE_NOW_ISO)


def utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=UTC)


def local_hour(text: str) -> int:
    return utc(text).astimezone(NOW.tzinfo).hour


@pytest.fixture(scope="module")
def tables() -> dict[str, list[dict]]:
    return G.generate_all()


def test_generator_is_deterministic_and_counts_match(tmp_path):
    outs = []
    for _ in range(2):
        out = tmp_path / f"run{len(outs)}"
        subprocess.run([sys.executable, str(ROOT / "data" / "generate.py"), "--out", str(out)], check=True, capture_output=True)
        digest = hashlib.sha256()
        for name in sorted(F.EXPECTED_ROW_COUNTS):
            data = (out / f"{name}.ndjson").read_bytes()
            assert data.count(b"\n") == F.EXPECTED_ROW_COUNTS[name], name
            digest.update(data)
        outs.append(digest.hexdigest())
        assert (out / "DATA_VERSION").read_text().startswith(F.DATA_VERSION)
    assert outs[0] == outs[1]


def test_generate_all_matches_expected_counts(tables):
    assert {k: len(v) for k, v in tables.items()} == F.EXPECTED_ROW_COUNTS
    assert list(tables) == list(F.EXPECTED_ROW_COUNTS)


def test_schemas_cover_every_generated_column(tables):
    for name, rows in tables.items():
        schema = json.loads((ROOT / "data" / "schemas" / f"{name}.json").read_text())
        cols = [f["name"] for f in schema]
        assert list(rows[0]) == cols, name
        required = {f["name"] for f in schema if f["mode"] == "REQUIRED"}
        for r in rows:
            assert all(r[c] is not None for c in required), (name, r)
    assert not (ROOT / "data" / "schemas" / "members.json").exists()
    assert not (ROOT / "data" / "schemas" / "salon_slots.json").exists()
    assert not (ROOT / "data" / "schemas" / "bookings.json").exists()


def test_vocabularies_and_invariants(tables):
    for i in tables["store_inventory"]:
        assert i["on_hand"] == i["on_shelf_qty"] + i["backroom_qty"]
        assert 0 <= i["on_shelf_qty"] and 0 <= i["backroom_qty"] and i["reorder_point"] >= 1
    for a in tables["associates"]:
        assert a["role"] in F.ROLES and set(a["skills"]) <= set(F.SKILLS)
        assert utc(a["shift_start"]) < utc(a["shift_end"])
    for t in tables["store_tasks"]:
        assert t["task_type"] in F.TASK_TYPES and t["status"] in F.TASK_STATUSES and t["source"] in F.TASK_SOURCES
        assert t["task_key"] is None and t["delegation_key"] is None
    assert {o["status"] for o in tables["bopis_orders"]} == set(F.BOPIS_STATUSES)
    assert {e["event_type"] for e in tables["shrink_events"]} == set(F.SHRINK_EVENT_TYPES)
    assert {f["topic"] for f in tables["guest_feedback"]} == set(F.FEEDBACK_TOPICS)
    assert {c["metric"] for c in tables["coaching_signals"]} == set(F.COACHING_METRICS)
    assert {r["status"] for r in tables["replenishment"]} == set(F.REPLENISHMENT_STATUSES)
    hours = {local_hour(t["ts_hour"]) for t in tables["store_traffic"]}
    assert hours == set(range(9, 21))
    assert all(1 <= f["rating"] <= 5 for f in tables["guest_feedback"])
    assert not any("@" in f["comment"] for f in tables["guest_feedback"])


def test_hero_store_product_and_people(tables):
    store = next(s for s in tables["stores"] if s["store_id"] == F.HERO_STORE_ID)
    assert store["city"] == F.HERO_STORE_CITY and store["name"] == F.HERO_STORE_NAME
    hero = next(p for p in tables["products"] if p["product_id"] == F.HERO_PRODUCT_ID)
    assert hero["name"] == F.HERO_PRODUCT_NAME and hero["is_fragrance_free"] and "sensitive" in hero["skin_types"]
    people = {a["associate_id"]: a for a in tables["associates"]}
    dana = people[F.HERO_MANAGER_ID]
    assert dana["first_name"] == F.HERO_MANAGER_FIRST_NAME and dana["role"] == "store_manager" and dana["store_id"] == F.HERO_STORE_ID
    priya = people[F.HERO_ASSOCIATE_ID]
    assert priya["first_name"] == F.HERO_ASSOCIATE_FIRST_NAME and priya["role"] == "associate" and priya["store_id"] == F.HERO_STORE_ID
    assert priya["skills"] == list(F.HERO_ASSOCIATE_SKILLS) and priya["current_task"] is None
    assert utc(priya["shift_start"]) == NOW and utc(priya["shift_end"]) == NOW + timedelta(hours=4)
    dm = people[F.HERO_DISTRICT_MANAGER_ID]
    assert dm["role"] == "district_manager" and dm["store_id"] == F.HERO_STORE_ID
    assert people[F.COACHING_ASSOCIATE_ID]["store_id"] == F.HERO_STORE_ID


def test_osa_exception_fixture(tables):
    inv = next(i for i in tables["store_inventory"] if i["store_id"] == F.HERO_STORE_ID and i["product_id"] == F.HERO_PRODUCT_ID)
    assert (inv["on_hand"], inv["on_shelf_qty"], inv["backroom_qty"], inv["reorder_point"], inv["shelf_capacity"]) == \
        (F.HERO_STORE_ON_HAND, F.HERO_STORE_ON_SHELF, F.HERO_STORE_BACKROOM, F.HERO_REORDER_POINT, F.HERO_SHELF_CAPACITY)
    repl = [r for r in tables["replenishment"] if r["store_id"] == F.HERO_STORE_ID and r["product_id"] == F.HERO_PRODUCT_ID]
    assert repl and all(r["status"] != "in_transit" for r in repl)
    open_hero = [t for t in tables["store_tasks"] if t["store_id"] == F.HERO_STORE_ID and t["product_id"] == F.HERO_PRODUCT_ID and t["status"] == "open"]
    assert open_hero == []


def test_bopis_backlog_fixture(tables):
    pending = [o for o in tables["bopis_orders"] if o["store_id"] == F.HERO_STORE_ID and o["status"] == "pending"]
    assert len(pending) == F.HERO_BOPIS_PENDING
    assert all(utc(o["promised_at"]) <= NOW + timedelta(hours=2) for o in pending)       # promised by 11:00 local
    assert sum(1 for o in pending if o["product_id"] == F.HERO_PRODUCT_ID) == F.HERO_BOPIS_PENDING_FOR_PRODUCT


def test_traffic_peak_fixture(tables):
    today = {local_hour(t["ts_hour"]): t["visitors"] for t in tables["store_traffic"]
             if t["store_id"] == F.HERO_STORE_ID and utc(t["ts_hour"]).astimezone(NOW.tzinfo).date() == NOW.date()}
    assert len(today) == 12
    assert all(today[h] >= 1.5 * today[9] for h in (10, 11, 12))


def test_shrink_pattern_fixture(tables):
    p = next(p for p in tables["products"] if p["product_id"] == F.SHRINK_PRODUCT_ID)
    assert p["category"] == "fragrance" and p["locked_case"] and p["name"] == F.SHRINK_PRODUCT_NAME
    recent = [e for e in tables["shrink_events"] if e["store_id"] == F.HERO_STORE_ID and e["product_id"] == F.SHRINK_PRODUCT_ID
              and NOW - timedelta(days=14) <= utc(e["event_ts"]) <= NOW]
    assert len(recent) == F.SHRINK_EVENTS_14D
    assert not any(k for k in recent[0] if "associate" in k or "name" in k)       # never names a person


def test_guest_feedback_and_coaching_fixtures(tables):
    low = [f for f in tables["guest_feedback"] if f["store_id"] == F.HERO_STORE_ID and f["rating"] <= 2
           and f["topic"] == "checkout_wait" and utc(f["submitted_at"]) >= NOW - timedelta(days=7)]
    assert len(low) == 2
    signal = next(c for c in tables["coaching_signals"] if c["associate_id"] == F.COACHING_ASSOCIATE_ID
                  and c["period"] == F.FIXTURE_WEEK and c["metric"] == "bopis_pick_rate")
    assert signal["value"] < 0.6
