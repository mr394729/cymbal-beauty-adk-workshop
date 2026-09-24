"""Generate the Cymbal Beauty store-operations dataset as newline-delimited JSON.

Deterministic: same seed, same frozen clock, same output every run (see fixtures.py).
Standard library only, so it runs before the project's virtualenv exists. `generate_all()` is the
single entry point: `main()` writes its tables to ndjson and `FakeBackend` serves them in memory,
so the unit tests and BigQuery always see the same rows.

Usage:  python data/generate.py [--out data/out]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fixtures as F  # noqa: E402

TZ = dt.timezone(dt.timedelta(hours=-5), F.FIXTURE_TIMEZONE)
NOW = dt.datetime.fromisoformat(F.FIXTURE_NOW_ISO)
TODAY = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
STORE_HOURS = list(range(9, 21))           # 12 hourly buckets a day, 09:00-20:59 local
TRAFFIC_DAYS = 14                          # today and the 13 days before it
HISTORY_DAYS = 14

# Category order decides the product-id ranges: skincare P-0001..0180, haircare ..0300, bath ..0380,
# fragrance ..0450 (so the shrink fixture P-0420 is a fragrance), makeup ..0600.
CATEGORIES = {
    "skincare": ["moisturizer", "cleanser", "serum", "sunscreen", "toner", "eye cream", "mask"],
    "haircare": ["shampoo", "conditioner", "hair mask", "leave-in", "styling cream", "dry shampoo"],
    "bath": ["body wash", "body lotion", "hand cream", "bath soak"],
    "fragrance": ["eau de parfum", "body mist", "rollerball"],
    "makeup": ["foundation", "concealer", "mascara", "lipstick", "blush", "eyeshadow palette"],
}
CATEGORY_SIZES = {"skincare": 180, "haircare": 120, "bath": 80, "fragrance": 70, "makeup": 150}
SKIN = ["dry", "oily", "combination", "sensitive", "normal"]
HAIR = ["straight", "wavy", "curly", "coily"]
INGREDIENTS = {
    "skincare": ["hyaluronic acid", "niacinamide", "ceramides", "vitamin C", "retinol", "squalane",
                 "glycerin", "salicylic acid", "peptides", "green tea", "centella", "zinc oxide"],
    "haircare": ["argan oil", "keratin", "biotin", "coconut oil", "shea butter", "rice water", "panthenol"],
    "makeup": ["hyaluronic acid", "vitamin E", "jojoba oil", "mica", "kaolin clay"],
    "fragrance": ["bergamot", "jasmine", "sandalwood", "vanilla", "vetiver", "pink pepper", "iris"],
    "bath": ["shea butter", "oat extract", "aloe", "coconut oil", "sea salt", "lavender"],
}
ADJ = ["Hydra", "Glow", "Velvet", "Bright", "Calm", "Renew", "Pure", "Silk", "Dew", "Lift", "Clear", "Bloom"]
CITIES = [
    ("Kansas City", "MO", "64105"), ("Chicago", "IL", "60611"), ("Bolingbrook", "IL", "60440"), ("Schaumburg", "IL", "60173"),
    ("Milwaukee", "WI", "53202"), ("Madison", "WI", "53703"), ("Indianapolis", "IN", "46204"), ("Columbus", "OH", "43215"),
    ("Cincinnati", "OH", "45202"), ("Detroit", "MI", "48226"), ("Grand Rapids", "MI", "49503"), ("Minneapolis", "MN", "55402"),
    ("St. Louis", "MO", "63101"), ("Naperville", "IL", "60540"), ("Nashville", "TN", "37203"), ("Louisville", "KY", "40202"),
    ("Atlanta", "GA", "30308"), ("Charlotte", "NC", "28202"), ("Raleigh", "NC", "27601"), ("Richmond", "VA", "23219"),
    ("Dallas", "TX", "75201"), ("Austin", "TX", "78701"), ("Houston", "TX", "77002"), ("Phoenix", "AZ", "85004"),
    ("Denver", "CO", "80202"), ("Salt Lake City", "UT", "84101"), ("Las Vegas", "NV", "89109"), ("Seattle", "WA", "98101"),
    ("Portland", "OR", "97205"), ("Sacramento", "CA", "95814"), ("San Jose", "CA", "95113"), ("Los Angeles", "CA", "90015"),
    ("San Diego", "CA", "92101"), ("Orlando", "FL", "32801"), ("Tampa", "FL", "33602"), ("Miami", "FL", "33131"),
    ("Boston", "MA", "02116"), ("Philadelphia", "PA", "19103"), ("Pittsburgh", "PA", "15222"), ("Newark", "NJ", "07102"),
]
FIRST = ["Priya", "Maya", "Ava", "Sofia", "Chloe", "Jordan", "Taylor", "Elena", "Aisha", "Nina", "Leah", "Zoe",
         "Camila", "Grace", "Harper", "Imani", "Jade", "Kira", "Lena", "Mia", "Noor", "Olivia", "Riley", "Sara",
         "Dana", "Marcus", "Theo", "Omar", "Felix", "Ravi"]
SHIFTS = [(8, 16), (9, 17), (9, 13), (12, 20), (13, 21)]
CURRENT_TASKS = ["cash wrap: register 1", "cash wrap: register 2", "backroom: receiving delivery",
                 "cycle count: haircare aisle", "planogram reset: makeup wall", "BOPIS picking"]
DISTRICT_MANAGER_IDS = {F.HERO_DISTRICT_MANAGER_ID, "A-1051", "A-1101", "A-1151"}
# The hero store's roster (associate_id, first_name, role, skills, shift start/end hour, current_task).
HERO_ROSTER = [
    ("A-1000", "Jordan", "associate", ["bopis", "makeup"], 9, 17, None),
    (F.HERO_DISTRICT_MANAGER_ID, "Elena", "district_manager", [], 8, 18, None),
    ("A-1002", "Maya", "associate", ["fragrance", "cash_wrap"], 9, 17, "cash wrap: register 1"),
    ("A-1003", "Aisha", "associate", ["bopis", "backroom"], 12, 21, None),
    (F.HERO_ASSOCIATE_ID, F.HERO_ASSOCIATE_FIRST_NAME, "associate", list(F.HERO_ASSOCIATE_SKILLS), 9, 13, None),
    ("A-1005", "Chloe", "associate", ["haircare", "makeup"], 9, 15, None),
    ("A-1006", "Taylor", "associate", ["bopis", "backroom"], 9, 17, "backroom: receiving delivery"),
    (F.COACHING_ASSOCIATE_ID, "Noor", "associate", ["bopis", "cash_wrap"], 9, 17, "cash wrap: register 2"),
]
FEEDBACK_COMMENTS = {
    "checkout_wait": {"low": ["Waited almost 15 minutes to pay with only one register open.",
                              "Checkout line was out the door on Saturday morning."],
                      "mid": ["Line moved slowly but the cashier was friendly."],
                      "high": ["In and out in five minutes, great."]},
    "associate_help": {"low": ["Could not find anyone to help me on the fragrance wall."],
                       "mid": ["Got help eventually, but had to ask twice."],
                       "high": ["An associate matched my foundation shade perfectly."]},
    "stock": {"low": ["The moisturizer I came for was not on the shelf again."],
              "mid": ["Half the shades were missing but they found one in the back."],
              "high": ["Everything on my list was in stock."]},
    "store_condition": {"low": ["Testers were empty and the makeup wall was a mess."],
                        "mid": ["Store was fine, a few empty shelves."],
                        "high": ["Clean, bright and well organised."]},
    "salon": {"low": ["My blowout appointment started 25 minutes late."],
              "mid": ["Salon was fine, nothing special."],
              "high": ["Best brow wax I have had."]},
}


def ts(d: dt.datetime) -> str:
    return d.astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def local(hour: int, minute: int = 0, day_offset: int = 0) -> dt.datetime:
    return TODAY + dt.timedelta(days=day_offset, hours=hour, minutes=minute)


def products(rng: random.Random) -> list[dict]:
    rows = []
    n = 0
    for cat, subs in CATEGORIES.items():
        for i in range(CATEGORY_SIZES[cat]):
            n += 1
            pid = f"P-{n:04d}"
            brand = rng.choice(F.BRANDS)
            sub = subs[i % len(subs)]
            name = f"{rng.choice(ADJ)} {sub.title()}"
            ff = rng.random() < (0.55 if cat in ("skincare", "bath") else 0.2) and cat != "fragrance"
            skin = ",".join(sorted(rng.sample(SKIN, rng.randint(1, 3)))) if cat in ("skincare", "makeup", "bath") else None
            hair = ",".join(sorted(rng.sample(HAIR, rng.randint(1, 3)))) if cat == "haircare" else None
            price = round(rng.choice([8.5, 12, 14, 18, 22, 24, 28, 32, 38, 45, 58, 72, 95]) + rng.choice([0, 0, 0.5, 0.99]), 2)
            ings = ",".join(rng.sample(INGREDIENTS[cat], rng.randint(2, 4)))
            clean = rng.random() < 0.4
            if pid == F.HERO_PRODUCT_ID:
                brand, name, sub, ff, skin, price = "Lumière Skin", F.HERO_PRODUCT_NAME, "moisturizer", True, "dry,sensitive", 28.0
            if pid == F.SHRINK_PRODUCT_ID:
                brand, name, sub, price = "Meridian Fragrance", F.SHRINK_PRODUCT_NAME, "eau de parfum", 95.0
            rows.append({
                "product_id": pid, "brand": brand, "name": name, "category": cat, "subcategory": sub,
                "price_usd": price, "is_fragrance_free": ff, "is_clean": clean,
                "locked_case": cat == "fragrance" and price >= 58,
                "skin_types": skin, "hair_types": hair, "key_ingredients": ings,
                "description": f"{name} by {brand}: a {sub} with {ings.replace(',', ', ')}.",
                "rating_avg": None, "rating_count": None,
            })
    assert len(rows) == F.EXPECTED_ROW_COUNTS["products"], len(rows)
    return rows


def stores(rng: random.Random) -> list[dict]:
    rows = []
    for i, (city, state, zip_) in enumerate(CITIES, start=1):
        sid = f"S-{i:03d}"
        has_salon = i % 4 != 0  # deterministic: 30 of 40 stores have a salon
        if sid == F.HERO_STORE_ID:
            assert city == F.HERO_STORE_CITY, (sid, city)
            has_salon = True
        rows.append({
            "store_id": sid, "name": f"Cymbal Beauty {city}", "city": city, "state": state, "zip": zip_,
            "has_salon": has_salon, "has_brow_bar": has_salon and rng.random() < 0.8,
            "opens": "09:00", "closes": "21:00",
            "lat": round(30 + rng.random() * 17, 4), "lng": round(-120 + rng.random() * 45, 4),
        })
    assert len(rows) == F.EXPECTED_ROW_COUNTS["stores"]
    return rows


def reviews(rng: random.Random, prods: list[dict]) -> list[dict]:
    rows = []
    phrases = {5: ("Holy grail", "Absolutely love this"), 4: ("Really good", "Works well for me"),
               3: ("It's fine", "Decent but not special"), 2: ("Not for me", "Broke me out a little"),
               1: ("Returned it", "Did nothing")}
    counts: dict[str, list[int]] = {}
    for i in range(F.EXPECTED_ROW_COUNTS["reviews"]):
        p = prods[i % len(prods)] if i < len(prods) else rng.choice(prods)
        rating = rng.choices([5, 4, 3, 2, 1], weights=[40, 30, 15, 10, 5])[0]
        if p["product_id"] == F.HERO_PRODUCT_ID:
            rating = rng.choice([5, 5, 4])
        skin = rng.choice(SKIN)
        created = NOW - dt.timedelta(days=rng.randint(1, 400), hours=rng.randint(0, 23))
        rows.append({
            "review_id": f"R-{i + 1:05d}", "product_id": p["product_id"],
            "rating": rating, "title": phrases[rating][0],
            "body": f"{phrases[rating][1]}. {p['name']} on {skin} skin.",
            "skin_type": skin, "created_at": ts(created),
        })
        counts.setdefault(p["product_id"], []).append(rating)
    for p in prods:
        rs = counts.get(p["product_id"], [])
        p["rating_avg"] = round(sum(rs) / len(rs), 2) if rs else None
        p["rating_count"] = len(rs) or None
    return rows


def inventory(rng: random.Random, prods: list[dict], sts: list[dict]) -> list[dict]:
    """on_hand = on_shelf_qty + backroom_qty for every row. About 4% of rows are out of stock, 5% below
    the reorder point and 1.5% of in-stock rows have nothing on the shelf (the OSA exception shape)."""
    rows = []
    updated = NOW - dt.timedelta(hours=2)
    for s in sts:
        for p in prods:
            cap = rng.choice([6, 8, 12, 18, 24])
            rp = max(2, cap // 4)
            r = rng.random()
            if r < 0.04:
                on_hand = 0
            elif r < 0.09:
                on_hand = rng.randint(1, rp - 1)
            else:
                on_hand = rng.randint(rp, cap + rng.choice([0, 2, 4, 6]))
            if on_hand == 0:
                shelf = 0
            elif rng.random() < 0.015:
                shelf = 0
            else:
                shelf = min(on_hand, cap, rng.randint(max(1, on_hand // 2), on_hand))
            bopis = on_hand > 0 and rng.random() < 0.9
            if s["store_id"] == F.HERO_STORE_ID and p["product_id"] == F.HERO_PRODUCT_ID:
                on_hand, shelf, rp, cap, bopis = F.HERO_STORE_ON_HAND, F.HERO_STORE_ON_SHELF, F.HERO_REORDER_POINT, F.HERO_SHELF_CAPACITY, True
                assert F.HERO_STORE_ON_HAND == F.HERO_STORE_ON_SHELF + F.HERO_STORE_BACKROOM
            rows.append({
                "store_id": s["store_id"], "product_id": p["product_id"], "on_hand": on_hand,
                "on_shelf_qty": shelf, "backroom_qty": on_hand - shelf, "reorder_point": rp, "shelf_capacity": cap,
                "bopis_eligible": bopis, "updated_at": ts(updated),
            })
    assert len(rows) == F.EXPECTED_ROW_COUNTS["store_inventory"]
    return rows


def associates(rng: random.Random, sts: list[dict]) -> list[dict]:
    """One store manager per store (U-M001..U-M040) plus 160 A-ids: the hero store's roster A-1000..A-1007
    (one of them the district manager), the rest round-robin over the other 39 stores with four district
    managers in total. Every row carries today's shift."""
    def person(aid, store_id, first, role, skills, start_h, end_h, task):
        return {"associate_id": aid, "store_id": store_id, "first_name": first, "role": role, "skills": list(skills),
                "shift_start": ts(local(start_h)), "shift_end": ts(local(end_h)), "current_task": task}

    rows = []
    for s in sts:
        n = int(s["store_id"][2:])
        first = rng.choice(FIRST)
        if s["store_id"] == F.HERO_STORE_ID:
            first = F.HERO_MANAGER_FIRST_NAME
        rows.append(person(f"U-M{n:03d}", s["store_id"], first, "store_manager", ["cash_wrap", "backroom"], 8, 17, None))
    for aid, first, role, skills, start_h, end_h, task in HERO_ROSTER:
        rows.append(person(aid, F.HERO_STORE_ID, first, role, skills, start_h, end_h, task))
    others = [s["store_id"] for s in sts if s["store_id"] != F.HERO_STORE_ID]
    for i in range(len(HERO_ROSTER), 160):
        aid = f"A-{1000 + i}"
        store_id = others[(i - len(HERO_ROSTER)) % len(others)]
        first = rng.choice(FIRST)
        start_h, end_h = rng.choice(SHIFTS)
        if aid in DISTRICT_MANAGER_IDS:
            rows.append(person(aid, store_id, first, "district_manager", [], 8, 18, None))
            continue
        skills = sorted(rng.sample(F.SKILLS, rng.randint(1, 3)))
        on_shift_now = start_h <= NOW.hour < end_h
        task = rng.choice(CURRENT_TASKS) if on_shift_now and rng.random() < 0.4 else None
        rows.append(person(aid, store_id, first, "associate", skills, start_h, end_h, task))
    assert len(rows) == F.EXPECTED_ROW_COUNTS["associates"], len(rows)
    return rows


def store_tasks(rng: random.Random, sts: list[dict], prods: list[dict], assocs: list[dict]) -> list[dict]:
    """Ten tasks per store over the last 14 days. The hero store's ten are hand-written so the history
    reads well in the demo and no open task exists for the hero product."""
    rows: list[dict] = []
    by_store: dict[str, list[str]] = {}
    for a in assocs:
        if a["role"] == "associate":
            by_store.setdefault(a["store_id"], []).append(a["associate_id"])

    def task(store_id, task_type, product_id, assignee_id, status, source, created, due_hours, note):
        rows.append({"task_id": f"T-{len(rows) + 1:05d}", "store_id": store_id, "task_type": task_type,
                     "product_id": product_id, "assignee_id": assignee_id, "status": status, "source": source,
                     "created_at": ts(created), "due_at": ts(created + dt.timedelta(hours=due_hours)), "note": note,
                     "task_key": None, "delegation_key": None})

    hero_tasks = [
        ("investigation", F.SHRINK_PRODUCT_ID, "A-1006", "done", "system", 10, 48, "Locked-case audit after two unknown-loss events; no cause found."),
        ("coaching", F.COACHING_ASSOCIATE_ID, None, "done", "manager", 8, 72, "BOPIS pick process refresher."),
        ("cycle_count", F.HERO_PRODUCT_ID, "A-1006", "done", "system", 5, 24, "Count matched the system: 12 on hand."),
        ("replenish", "P-0388", "A-1003", "done", "agent", 3, 24, "Case pack received and shelved."),
        ("coverage_move", None, None, "cancelled", "manager", 6, 4, "Saturday coverage move cancelled; volume did not materialise."),
        ("backroom_check", "P-0512", "A-1006", "done", "agent", 1, 4, "Two units moved from backroom to shelf."),
        ("planogram_fix", "P-0233", "A-1005", "open", "system", 2, 48, "Haircare endcap does not match the October planogram."),
        ("cycle_count", "P-0301", "A-1006", "open", "system", 1, 24, "Variance flagged by the nightly count."),
        ("signage_fix", None, None, "open", "system", 1, 24, "Promo sign missing on the skincare gondola."),
        ("replenish", "P-0455", None, "open", "manager", 0, 8, "Foundation shades 220-240 below reorder point."),
    ]
    for s in sts:
        sid = s["store_id"]
        if sid == F.HERO_STORE_ID:
            for task_type, pid, aid_or_target, status, source, days_ago, due_h, note in hero_tasks:
                created = NOW - dt.timedelta(days=days_ago, hours=rng.randint(0, 6))
                assignee = aid_or_target if task_type != "coaching" else F.HERO_MANAGER_ID
                product = pid if task_type != "coaching" else None
                task(sid, task_type, product, assignee, status, source, created, due_h, note)
            continue
        for _ in range(10):
            created = NOW - dt.timedelta(days=rng.randint(0, HISTORY_DAYS - 1), hours=rng.randint(0, 10))
            task_type = rng.choice(F.TASK_TYPES)
            product = rng.choice(prods)["product_id"] if task_type not in ("coverage_move", "signage_fix", "coaching") and rng.random() < 0.85 else None
            assignee = rng.choice(by_store[sid]) if rng.random() < 0.7 else None
            age_days = (NOW - created).days
            status = rng.choices(["done", "cancelled", "open"], weights=[75, 5, 20] if age_days >= 2 else [40, 5, 55])[0]
            source = rng.choices(F.TASK_SOURCES, weights=[40, 35, 25])[0]
            task(sid, task_type, product, assignee, status, source, created, rng.choice([4, 8, 24, 48]),
                 f"{task_type.replace('_', ' ').capitalize()} raised by {source}.")
    assert len(rows) == F.EXPECTED_ROW_COUNTS["store_tasks"], len(rows)
    return rows


def bopis_orders(rng: random.Random, sts: list[dict], inv: list[dict]) -> list[dict]:
    """Fifty orders per store. At the hero store exactly HERO_BOPIS_PENDING are pending, all promised by
    11:00 today, HERO_BOPIS_PENDING_FOR_PRODUCT of them for the hero product; the rest are already picked,
    ready or collected."""
    rows: list[dict] = []
    eligible: dict[str, list[str]] = {}
    for i in inv:
        if i["bopis_eligible"]:
            eligible.setdefault(i["store_id"], []).append(i["product_id"])

    def order(store_id, product_id, qty, promised, status):
        rows.append({"order_id": f"BO-{len(rows) + 1:06d}", "store_id": store_id, "product_id": product_id,
                     "qty": qty, "promised_at": ts(promised), "status": status})

    for s in sts:
        sid = s["store_id"]
        pool = [p for p in eligible[sid] if p != F.HERO_PRODUCT_ID]
        if sid == F.HERO_STORE_ID:
            slots = [local(9, 30), local(9, 45), local(10, 0), local(10, 15), local(10, 30), local(10, 30),
                     local(10, 45), local(11, 0), local(11, 0)]
            for k, promised in enumerate(slots):
                pid = F.HERO_PRODUCT_ID if k < F.HERO_BOPIS_PENDING_FOR_PRODUCT else rng.choice(pool)
                order(sid, pid, rng.choice([1, 1, 2]), promised, "pending")
            for _ in range(50 - len(slots)):
                status = rng.choices(["picked", "ready", "collected"], weights=[15, 25, 60])[0]
                promised = NOW - dt.timedelta(days=rng.randint(0, 3), hours=rng.randint(0, 11)) if status == "collected" \
                    else local(rng.randint(13, 20), rng.choice([0, 30]))
                order(sid, rng.choice(pool), rng.choice([1, 1, 2, 3]), promised, status)
            continue
        for _ in range(50):
            status = rng.choices(F.BOPIS_STATUSES, weights=[20, 15, 25, 40])[0]
            if status == "pending":
                promised = local(rng.randint(9, 20), rng.choice([0, 15, 30, 45]))
            elif status == "collected":
                promised = NOW - dt.timedelta(days=rng.randint(0, 3), hours=rng.randint(0, 11))
            else:
                promised = local(rng.randint(9, 20), rng.choice([0, 30]))
            order(sid, rng.choice(eligible[sid]), rng.choice([1, 1, 2, 3]), promised, status)
    assert len(rows) == F.EXPECTED_ROW_COUNTS["bopis_orders"], len(rows)
    return rows


def store_traffic(rng: random.Random, sts: list[dict]) -> list[dict]:
    """Hourly visitors, transactions and sales for the last 14 days including today (today's rows are the
    store's expected traffic, which the daily plan reads as the forecast). The hero store peaks 10:00-12:00."""
    rows = []
    curve = [0.45, 0.7, 0.9, 1.0, 1.0, 0.95, 0.85, 0.8, 0.9, 0.9, 0.7, 0.5]   # 09:00 .. 20:00
    hero_today = {9: 40, 10: 72, 11: 88, 12: 80}
    for s in sts:
        base = rng.randint(30, 80)
        ticket = rng.uniform(28, 52)
        for day_offset in range(-(TRAFFIC_DAYS - 1), 1):
            day = TODAY + dt.timedelta(days=day_offset)
            weekend = 1.3 if day.weekday() >= 5 else 1.0
            for h, c in zip(STORE_HOURS, curve, strict=True):
                visitors = int(base * c * weekend * rng.uniform(0.85, 1.15))
                if s["store_id"] == F.HERO_STORE_ID and day_offset == 0 and h in hero_today:
                    visitors = hero_today[h]
                transactions = int(visitors * rng.uniform(0.3, 0.45))
                rows.append({"store_id": s["store_id"], "ts_hour": ts(day + dt.timedelta(hours=h)),
                             "visitors": visitors, "transactions": transactions,
                             "sales_usd": round(transactions * ticket * rng.uniform(0.9, 1.1), 2)})
    assert len(rows) == F.EXPECTED_ROW_COUNTS["store_traffic"], len(rows)
    return rows


def shrink_events(rng: random.Random, sts: list[dict], prods: list[dict]) -> list[dict]:
    """37 events per store over the last 28 days, plus the hero pattern (SHRINK_EVENTS_14D events for the
    locked-case fragrance P-0420 at S-014 in the last 14 days, two older ones) and three-event clusters at
    four other stores that stay below the investigate threshold."""
    rows: list[dict] = []
    price = {p["product_id"]: p["price_usd"] for p in prods}
    pids = [p["product_id"] for p in prods]
    cheap = [p["product_id"] for p in prods if p["price_usd"] < 60 and not p["locked_case"]]

    def event(store_id, product_id, event_type, qty, event_ts):
        rows.append({"event_id": f"SE-{len(rows) + 1:05d}", "store_id": store_id, "product_id": product_id,
                     "event_type": event_type, "qty": qty, "value_usd": round(qty * price[product_id], 2),
                     "event_ts": ts(event_ts)})

    for s in sts:
        for _ in range(37):
            pid = rng.choice(pids)
            while s["store_id"] == F.HERO_STORE_ID and pid == F.SHRINK_PRODUCT_ID:
                pid = rng.choice(pids)
            when = NOW - dt.timedelta(days=rng.randint(0, 27), hours=rng.randint(1, 12))
            event(s["store_id"], pid, rng.choices(F.SHRINK_EVENT_TYPES, weights=[35, 30, 20, 15])[0], rng.choice([1, 1, 1, 2]), when)
    hero_pattern = [("unknown_loss", 1, 1), ("unknown_loss", 2, 3), ("damage", 1, 5), ("return_anomaly", 1, 7),
                    ("unknown_loss", 1, 9), ("adjustment", 1, 12)]
    for event_type, qty, days_ago in hero_pattern:
        event(F.HERO_STORE_ID, F.SHRINK_PRODUCT_ID, event_type, qty, NOW - dt.timedelta(days=days_ago, hours=3))
    for days_ago in (20, 24):
        event(F.HERO_STORE_ID, F.SHRINK_PRODUCT_ID, "unknown_loss", 1, NOW - dt.timedelta(days=days_ago, hours=5))
    for sid in ("S-002", "S-021", "S-028", "S-036"):
        pid = rng.choice(cheap)
        for days_ago in (2, 6, 11):
            event(sid, pid, "damage", 1, NOW - dt.timedelta(days=days_ago, hours=4))
    assert len(rows) == F.EXPECTED_ROW_COUNTS["shrink_events"], len(rows)
    return rows


def guest_feedback(rng: random.Random, sts: list[dict]) -> list[dict]:
    """Twenty synthetic comments per store over the last 14 days; no names, emails or phone numbers.
    The hero store has exactly two low checkout-wait ratings in the last 7 days."""
    rows: list[dict] = []

    def feedback(store_id, submitted, rating, topic):
        band = "low" if rating <= 2 else "mid" if rating == 3 else "high"
        rows.append({"feedback_id": f"GF-{len(rows) + 1:05d}", "store_id": store_id, "submitted_at": ts(submitted),
                     "rating": rating, "topic": topic, "comment": rng.choice(FEEDBACK_COMMENTS[topic][band])})

    for s in sts:
        sid = s["store_id"]
        topics = list(F.FEEDBACK_TOPICS) if s["has_salon"] else [t for t in F.FEEDBACK_TOPICS if t != "salon"]
        n = 20
        if sid == F.HERO_STORE_ID:
            feedback(sid, NOW - dt.timedelta(days=2, hours=4), 1, "checkout_wait")
            feedback(sid, NOW - dt.timedelta(days=4, hours=7), 2, "checkout_wait")
            n -= 2
        for _ in range(n):
            rating = rng.choices([5, 4, 3, 2, 1], weights=[38, 30, 14, 12, 6])[0]
            topic = rng.choice(topics)
            if sid == F.HERO_STORE_ID and rating <= 2 and topic == "checkout_wait":
                topic = "stock"
            submitted = NOW - dt.timedelta(days=rng.randint(0, HISTORY_DAYS - 1), hours=rng.randint(1, 12))
            feedback(sid, submitted, rating, topic)
    assert len(rows) == F.EXPECTED_ROW_COUNTS["guest_feedback"], len(rows)
    return rows


def coaching_signals(rng: random.Random, assocs: list[dict]) -> list[dict]:
    """Four metrics for FIXTURE_WEEK per associate (role associate only); the coaching fixture has a low pick rate."""
    rows = []
    ranges = {"bopis_pick_rate": (0.62, 0.98), "cycle_count_accuracy": (0.85, 0.995),
              "guest_rating": (3.6, 4.9), "task_completion": (0.7, 1.0)}
    for a in assocs:
        if a["role"] != "associate":
            continue
        for metric in F.COACHING_METRICS:
            lo, hi = ranges[metric]
            value = round(rng.uniform(lo, hi), 2)
            if a["associate_id"] == F.COACHING_ASSOCIATE_ID and metric == "bopis_pick_rate":
                value = F.COACHING_LOW_PICK_RATE
            rows.append({"associate_id": a["associate_id"], "period": F.FIXTURE_WEEK, "metric": metric, "value": value})
    assert len(rows) == F.EXPECTED_ROW_COUNTS["coaching_signals"], len(rows)
    return rows


def replenishment(rng: random.Random, sts: list[dict], prods: list[dict]) -> list[dict]:
    """Thirty inbound lines per store. The hero product's line at the hero store is delayed (nothing in transit),
    which is why the OSA rule recommends a replenishment."""
    rows = []
    pids = [p["product_id"] for p in prods if p["product_id"] != F.HERO_PRODUCT_ID]
    for s in sts:
        sid = s["store_id"]
        n = 30
        if sid == F.HERO_STORE_ID:
            rows.append({"store_id": sid, "product_id": F.HERO_PRODUCT_ID, "expected_at": ts(NOW - dt.timedelta(days=2)),
                         "qty": 12, "status": "delayed"})
            n -= 1
        for _ in range(n):
            status = rng.choices(F.REPLENISHMENT_STATUSES, weights=[45, 30, 15, 10])[0]
            if status in ("scheduled", "in_transit"):
                expected = NOW + dt.timedelta(days=rng.randint(1, 7), hours=rng.randint(0, 8))
            else:
                expected = NOW - dt.timedelta(days=rng.randint(1, 5), hours=rng.randint(0, 8))
            rows.append({"store_id": sid, "product_id": rng.choice(pids), "expected_at": ts(expected),
                         "qty": rng.choice([6, 12, 12, 24]), "status": status})
    assert len(rows) == F.EXPECTED_ROW_COUNTS["replenishment"], len(rows)
    return rows


def generate_all(seed: int = 42) -> dict[str, list[dict]]:
    """Every table, in load order, from one seeded generator."""
    rng = random.Random(seed)
    prods = products(rng)
    sts = stores(rng)
    revs = reviews(rng, prods)
    inv = inventory(rng, prods, sts)
    assocs = associates(rng, sts)
    tasks = store_tasks(rng, sts, prods, assocs)
    orders = bopis_orders(rng, sts, inv)
    traffic = store_traffic(rng, sts)
    shrink = shrink_events(rng, sts, prods)
    feedback = guest_feedback(rng, sts)
    coaching = coaching_signals(rng, assocs)
    repl = replenishment(rng, sts, prods)
    from agents.cymbal_store_ops.operations_fixtures import operations_snapshots

    tables = {"products": prods, "reviews": revs, "stores": sts, "store_inventory": inv, "associates": assocs,
              "store_tasks": tasks, "bopis_orders": orders, "store_traffic": traffic, "shrink_events": shrink,
              "guest_feedback": feedback, "coaching_signals": coaching, "replenishment": repl, "operations_context": operations_snapshots()}
    assert list(tables) == list(F.EXPECTED_ROW_COUNTS), "table order must match EXPECTED_ROW_COUNTS"
    return tables


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "out"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tables = generate_all()
    digest = hashlib.sha256()
    for name, rows in tables.items():
        path = out / f"{name}.ndjson"
        with path.open("w") as fh:
            for r in rows:
                line = json.dumps(r, ensure_ascii=False)
                fh.write(line + "\n")
                digest.update(line.encode())
        expected = F.EXPECTED_ROW_COUNTS[name]
        if len(rows) != expected:
            print(f"ERROR: {name}: generated {len(rows)} rows, expected {expected}", file=sys.stderr)
            return 1
        print(f"{name:16s} {len(rows):6d} rows -> {path}")
    (out / "DATA_VERSION").write_text(f"{F.DATA_VERSION}\nsha256:{digest.hexdigest()}\n")
    print(f"DATA_VERSION {F.DATA_VERSION} sha256:{digest.hexdigest()[:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
