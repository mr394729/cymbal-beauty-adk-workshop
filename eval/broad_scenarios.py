"""Seeded broad questions with independent raw-data oracles, never tool trajectories.

Reads generated NDJSON (or an independently captured data snapshot). It imports no
agent tools, prompts, backend implementation or fixture answer constants.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

TABLES = ("products", "store_inventory", "bopis_orders", "store_tasks", "store_traffic", "replenishment",
          "associates", "shrink_events", "guest_feedback", "coaching_signals", "operations_context", "reviews")
NOW = datetime.fromisoformat("2026-10-03T09:00:00-05:00")
STORE = "S-014"
IDENTITIES = {
    "manager": {"user:user_id": "U-M014", "user:store_id": STORE, "user:role": "store_manager", "user:first_name": "Dana"},
    "associate": {"user:user_id": "A-1004", "user:store_id": STORE, "user:role": "associate", "user:first_name": "Priya"},
}


def timestamp(value):
    return datetime.fromisoformat(value.replace(" UTC", "+00:00")).astimezone(NOW.tzinfo)


def aggregate(rows, key, sums=()):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row[key]].append(row)
    return [{key: group, "record_count": len(items), **{field: round(sum(item[field] for item in items), 2)
                                                     for field in sums}}
            for group, items in sorted(grouped.items())]


def load_data(folder: Path):
    tables, hashes = {}, {}
    for table in TABLES:
        path = folder / f"{table}.ndjson"
        raw = path.read_bytes()
        hashes[table] = hashlib.sha256(raw).hexdigest()
        tables[table] = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    return tables, hashes


def build_dataset(folder: Path, *, seed=20260921):
    data, hashes = load_data(folder)
    rng = random.Random(seed)
    products = {r["product_id"]: r for r in data["products"]}
    scoped = {name: [r for r in rows if r.get("store_id", STORE) == STORE] for name, rows in data.items()}
    inventory = [{**products[r["product_id"]], **r} for r in scoped["store_inventory"]]
    by_id = {r["product_id"]: r for r in inventory}
    orders, tasks, roster = scoped["bopis_orders"], scoped["store_tasks"], scoped["associates"]
    pending = [r for r in orders if r["status"] == "pending"]
    open_tasks = [r for r in tasks if r["status"] == "open"]
    ops = {(r["system"], r["subject_id"]): json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"]
           for r in scoped["operations_context"]}
    cases = []

    def add(domain, question, facts, criteria, *, persona="manager", turns=None):
        number = len(cases) + 1
        oracle = [{"id": key, "value": value} for key, value in facts.items()]
        first = {"question": question, "oracle": oracle, "criteria": criteria}
        cases.append({"id": f"broad-{number:02d}", "domain": domain, "persona": persona,
                      "turns": [first] + (turns or [])})

    def stock_totals(rows):
        return {"sku_count": len(rows), "on_hand_units": sum(r["on_hand"] for r in rows),
                "shelf_units": sum(r["on_shelf_qty"] for r in rows), "backroom_units": sum(r["backroom_qty"] for r in rows),
                "zero_on_hand_skus": sum(r["on_hand"] == 0 for r in rows),
                "refillable_empty_shelf_skus": sum(r["on_shelf_qty"] == 0 and r["backroom_qty"] > 0 for r in rows),
                "below_reorder_skus": sum(r["on_hand"] < r["reorder_point"] for r in rows),
                "by_category": aggregate(rows, "category", ("on_hand", "on_shelf_qty", "backroom_qty"))}

    arbitrary = rng.sample([r for r in inventory if r["product_id"] not in {"P-0101", "P-0420", "P-0548"}], 3)
    for row in arbitrary[:2]:
        add("inventory", f"What do we actually have of {row['name']} ({row['product_id']})? Separate what's on the shelf from what's in back.",
            {"stock": row}, ["Report exact shelf, backroom and total quantities for the requested SKU; do not substitute a familiar product."])
    for category in ("skincare", "makeup", "haircare"):
        rows = [r for r in inventory if r["category"] == category]
        add("inventory", f"Give me the {category} stock picture for the whole store: product count and units, split shelf and backroom.",
            {"category_totals": stock_totals(rows)}, ["Cover the whole requested category, with correct SKU and unit totals, not only exceptions."])
    add("inventory", "How many different products and total units do we have across the entire store? Break it down by category.",
        {"inventory_totals": stock_totals(inventory)}, ["Give complete store SKU/unit totals and category breakdown; do not present low-stock exceptions as the full assortment."])
    zero = [r for r in inventory if r["on_hand"] == 0]
    add("inventory", "Which products are completely out of stock, not just off the shelf? Give me the total and up to three examples.",
        {"zero_stock_count": len(zero), "valid_examples": zero}, ["Distinguish total zero from shelf zero, state exact count and up to three actual examples; if none, say so."])
    shelf_gap = [r for r in inventory if r["on_shelf_qty"] == 0 and r["backroom_qty"] > 0]
    add("inventory", "How many empty shelf lines could we refill from recorded backstock? Show five examples without creating tasks.",
        {"gap_count": len(shelf_gap), "valid_examples": shelf_gap}, ["Count shelf-zero/backroom-positive SKUs and identify up to five real examples; propose no completed write."])
    below = [r for r in inventory if r["on_hand"] < r["reorder_point"]]
    add("inventory", "Show me five products below their reorder point, with the stock gap for each.",
        {"valid_products": [{"product_id": r["product_id"], "name": r["name"], "on_hand": r["on_hand"],
                             "reorder_point": r["reorder_point"], "gap": r["reorder_point"] - r["on_hand"]} for r in below]},
        ["Select up to five actual below-reorder products and calculate gaps correctly; no double subtraction of demand."])
    locked = [r for r in inventory if r["category"] == "fragrance" and r["locked_case"]]
    add("inventory", "How much fragrance stock is in locked-case lines, in total?", {"locked_fragrance": stock_totals(locked)},
        ["Return units and SKU count for locked-case fragrance, not the entire fragrance category."])
    top = sorted([r for r in inventory if r["category"] == "skincare"], key=lambda r: (-r["backroom_qty"], r["product_id"]))
    add("inventory", "Which three skincare products have the largest backroom quantities?", {"ranked_products": [r for r in top if r["backroom_qty"] >= top[2]["backroom_qty"]]},
        ["Return top three backroom quantities with products; accept any tied SKU at the third-place boundary."])
    a, b = arbitrary[:2]
    add("inventory", f"Compare stock for {a['product_id']} and {b['product_id']}. Which has more shelf stock and by how much?",
        {"first": a, "second": b, "shelf_difference": abs(a["on_shelf_qty"] - b["on_shelf_qty"])},
        ["Resolve both specified SKUs and compare shelf units correctly, including a tie if applicable."])

    add("orders", "How many pickup orders are still pending, and how many units is that? When is the next promise?",
        {"pending_orders": len(pending), "pending_units": sum(r["qty"] for r in pending),
         "first_promise": min((r["promised_at"] for r in pending), default=None)},
        ["Keep orders separate from units and give the earliest pending promise in store-local time."])
    due = [r for r in pending if NOW <= timestamp(r["promised_at"]) <= NOW + timedelta(hours=1)]
    add("orders", "Which pickups are due in the next hour, and how many units do we need to pick for them?",
        {"due_orders": due, "unit_total": sum(r["qty"] for r in due), "window": [NOW.isoformat(), (NOW + timedelta(hours=1)).isoformat()]},
        ["Use 9–10 a.m. store-local window, preserve individual promises and sum the correct units."])
    hero = [r for r in pending if r["product_id"] == "P-0101"]
    add("orders", "Can the Lumière Hydra Cream backstock cover all its pickup commitments and leave anything for the shelf?",
        {"stock": by_id["P-0101"], "pending": hero, "allocation": ops.get(("inventory_allocation", "P-0101")),
         "unit_demand": sum(r["qty"] for r in hero)},
        ["Distinguish active reservations from pending demand; do not subtract the same committed units twice; compute remaining shelf allocation."])
    ready = [r for r in orders if r["status"] == "ready"]
    add("orders", "How many orders are ready for collection? Don't include ones still being picked.",
        {"ready_count": len(ready), "ready_units": sum(r["qty"] for r in ready)}, ["Count only ready status, not pending/picked/collected."])
    add("orders", "Break our pending pickup units down by product category.",
        {"by_category": aggregate([{**r, "category": products[r["product_id"]]["category"]} for r in pending], "category", ("qty",))},
        ["Aggregate pending units by category and distinguish unit totals from order counts."])
    order = rng.choice(orders)
    add("orders", f"What's the current situation with order {order['order_id']}?", {"order": order, "product": products[order["product_id"]]},
        ["Report exact order status, product, units and promise without treating a past promise as current pickup completion."])

    deliveries = scoped["replenishment"]
    delayed = [r for r in deliveries if r["status"] == "delayed"]
    add("supply", "Which replenishment deliveries are delayed? Give the number of delivery records and affected units.",
        {"delayed": delayed, "records": len(delayed), "units": sum(r["qty"] for r in delayed)},
        ["Count delayed records and units accurately, identify affected products; don't invent a new arrival estimate."])
    incoming = next((r for r in deliveries if r["product_id"] not in {"P-0101", "P-0420"}), deliveries[0])
    add("supply", f"Is anything coming in for {incoming['product_id']}? Tell me quantities, timing and status.",
        {"product": products[incoming["product_id"]], "deliveries": [r for r in deliveries if r["product_id"] == incoming["product_id"]]},
        ["Include all matching inbound records, retain delayed/received distinctions and local dates."])
    transit = [r for r in deliveries if r["status"] == "in_transit"]
    add("supply", "How many units are currently in transit to us, across all products?", {"records": transit, "units": sum(r["qty"] for r in transit)},
        ["Sum in-transit units only; don't mix scheduled, delayed or received quantities."])
    add("supply", "Hydra Cream's delivery is late. What can we do from current stock today, and what is still uncertain?",
        {"stock": by_id["P-0101"], "delivery": [r for r in deliveries if r["product_id"] == "P-0101"],
         "pending": hero, "location": ops.get(("stock_location", "P-0101")), "allocation": ops.get(("inventory_allocation", "P-0101"))},
        ["Use current backstock for recorded commitments and shelf remainder; distinguish delayed supply from known current quantities."])

    add("coverage", "Who could cover pickups until 11 without leaving checkout short?", {"roster": roster, "open_tasks": open_tasks,
        "coverage": ops.get(("coverage", "store")), "pending": pending},
        ["Recommend someone on shift with relevant skills, respecting existing assignments, protected checkout and breaks; no writes."])
    add("coverage", "Priya is unavailable until 10. Who else can handle the morning pickups?", {"roster": roster, "open_tasks": open_tasks,
        "coverage": ops.get(("coverage", "store")), "user_constraint": "Priya unavailable until 10", "pending": pending},
        ["Respect the explicit availability change without pretending it changed roster records; propose a feasible alternate."])
    personal = [r for r in tasks if r.get("assignee_id") == "A-1004"]
    add("personal", "What is my shift, and which of my tasks are still open?", {"person": next(r for r in roster if r["associate_id"] == "A-1004"),
        "assigned_open_tasks": [r for r in personal if r["status"] == "open"]}, ["Use signed-in Priya's shift and own open tasks only."], persona="associate")
    add("tasks", "Give me a count of all open store tasks by type, with assigned versus unassigned totals.",
        {"by_type": aggregate(open_tasks, "task_type"), "assigned": sum(bool(r.get("assignee_id")) for r in open_tasks),
         "unassigned": sum(not r.get("assignee_id") for r in open_tasks)}, ["Aggregate every open task; distinguish assignment totals and do not count completed tasks."])
    overdue = [r for r in open_tasks if timestamp(r["due_at"]) < NOW]
    add("tasks", "Which open tasks are already overdue as of this morning?", {"overdue": overdue, "now": NOW.isoformat()},
        ["Compare actual deadlines to9a.m.; exclude completed tasks and tasks due later today; say none if empty."])
    early = [r for r in open_tasks if timestamp(r["due_at"]) <= NOW + timedelta(hours=2)]
    add("tasks", "What open work is due by 11, and who owns it?", {"due_by_eleven": early, "roster": roster},
        ["Cover all open tasks due by11a.m. including overdue ones; name actual owner or unassigned status."])

    yesterday = [r for r in scoped["store_traffic"] if timestamp(r["ts_hour"]).date() == (NOW - timedelta(days=1)).date()]
    today = [r for r in scoped["store_traffic"] if timestamp(r["ts_hour"]).date() == NOW.date()]
    metrics = {k: round(sum(r[k] for r in yesterday), 2) for k in ("visitors", "transactions", "sales_usd")}
    add("traffic", "How did we do yesterday on sales, visitors and transactions?", {"yesterday_totals": metrics, "date": str((NOW-timedelta(days=1)).date())},
        ["Aggregate yesterday's store records only; state correct sales, visitor and transaction totals."])
    add("traffic", "When is today's biggest traffic hour, and how busy is it compared with opening?", {"today": today, "current_day_rows_are_forecasts": True},
        ["Identify maximum recorded visitors and compare with9a.m.; explain if records are observations/planning data without inventing future certainty."])
    conversion = round(metrics["transactions"] / metrics["visitors"] * 100, 2) if metrics["visitors"] else None
    add("traffic", "What was yesterday's conversion rate, using transactions divided by visitors?", {"totals": metrics, "conversion_percent": conversion},
        ["Calculate transactions/visitors correctly, state denominator and reasonable rounding; don't substitute sales or guest ratings."])

    loss = [r for r in scoped["shrink_events"] if NOW - timedelta(days=14) <= timestamp(r["event_ts"]) <= NOW]
    loss_facts = {"events": len(loss), "units": sum(r["qty"] for r in loss), "value_usd": round(sum(r["value_usd"] for r in loss),2),
                  "by_type": aggregate(loss,"event_type",("qty","value_usd"))}
    add("loss", "Summarize the last two weeks of recorded store loss by type, separating events, units and value.", {"loss": loss_facts},
        ["Keep event counts, units and dollars distinct; preserve known damage versus unknown loss and14-day window."])
    loss_sku = rng.choice([r["product_id"] for r in loss if r["product_id"] != "P-0420"])
    add("loss", f"What loss records do we have for {loss_sku} in the last 14 days?", {"product":products[loss_sku], "events":[r for r in loss if r["product_id"] == loss_sku]},
        ["Answer for the requested arbitrary SKU and exact period; no attribution of blame or blanket theft claim."])
    add("loss", "What exactly needs checking on the Noir Velvet case, based on recorded control findings?",
        {"controls":ops.get(("loss_controls","P-0420")),"tasks":[r for r in tasks if r.get("product_id") == "P-0420"]},
        ["Use actual recorded control findings; preserve identifier types (check IDs are not fixture IDs). Do not claim the latch finding proves theft or causes all losses."])
    add("loss", "Which category has the highest recorded loss value over the last two weeks?",
        {"categories":aggregate([{**r,"category":products[r["product_id"]]["category"]} for r in loss],"category",("qty","value_usd"))},
        ["Rank category by dollar value, not event count/units, and state the winning value."])

    feedback=[r for r in scoped["guest_feedback"] if NOW-timedelta(days=7) <= timestamp(r["submitted_at"]) <= NOW]
    add("feedback","What are guests telling us this week? Give the average rating and the main recurring issues.",
        {"reviews":feedback,"review_count":len(feedback),"average":round(sum(r["rating"] for r in feedback)/len(feedback),2) if feedback else None},
        ["Ground themes in actual comments; correct rating and review denominator; do not infer a named SKU from generic complaints."])
    checkout=[r for r in feedback if r["topic"] == "checkout_wait" and r["rating"] <= 2]
    add("feedback","How many low-rated checkout complaints did we get in the last week, and what did they say?",
        {"low_rating_definition":"1 or2 stars","reviews":checkout},["Use checkout-only1–2star feedback, give count and faithful themes."])
    add("feedback","Are stock complaints or checkout complaints getting worse ratings this week?",
        {"topic_ratings":{topic:{"count":len(rows),"average":round(sum(r["rating"] for r in rows)/len(rows),2) if rows else None}
                           for topic in ("stock","checkout_wait") for rows in [[r for r in feedback if r["topic"] == topic]]}},
        ["Compare topic means with denominators; lower rating is worse. Dated observations in the raw reviews are valid evidence; do not invent a prior-period comparison or a causal operational explanation."])
    add("merchandising","What display or signage changes are scheduled today, and which deadlines matter first?",
        {"directives":ops.get(("directives","store"))},["Use approved recorded work and deadlines; separate tasks proposed from tasks already done."])
    add("merchandising","Can we finish the skincare display and honor Hydra Cream pickups from today's stock?",
        {"directives":ops.get(("directives","store")),"stock":by_id["P-0101"],"pending":hero,"allocation":ops.get(("inventory_allocation","P-0101"))},
        ["Connect current units, pickup commitments and display deadline; avoid allocating the same units twice."])
    def development(person):
        return {"activity":ops.get(("picking_activity",person)),"learning":ops.get(("learning",person)),
                "signals":[r for r in data["coaching_signals"] if r["associate_id"] == person]}
    add("development","What support would help Noor with picking? Keep it practical and evidence-based.",development("A-1007"),
        ["Use dated activity and denominators; choose relevant support; don't interpret legacy unspecified index as a documented rate."])
    add("development","I have ten minutes for learning. What should I practice based on my recent work?",development("A-1004"),
        ["Use signed-in Priya's activity and available learning; no manager-only coaching of peers."],persona="associate")
    add("development","Compare Noor and Priya's picking support needs without turning this into a performance ranking.",
        {"Noor":development("A-1007"),"Priya":development("A-1004")},
        ["Distinguish each person's actual signals; compare rates with denominators where relevant; suggest support without disciplinary ranking."])
    catalog=[r for r in inventory if r["is_fragrance_free"] and r["category"] == "skincare" and r["subcategory"] == "moisturizer" and r["price_usd"] <= 30 and r["on_hand"] > 0]
    add("guest","A guest wants a fragrance-free moisturizer under $30. What can we offer from current stock?",{"eligible_options":catalog},
        ["Offer matching recorded products, prices and availability; don't invent clinical benefits."],persona="associate")
    hair=[r for r in inventory if r["category"] == "haircare" and r["on_hand"] > 0 and r["price_usd"] <= 25]
    add("guest","Show me two haircare choices under $25 that we actually have available.",{"eligible_options":hair},
        ["Return up to two matching stocked products with correct prices and relevant recorded features."],persona="associate")
    sensitive=[r for r in inventory if r["category"] == "skincare" and "sensitive" in (r.get("skin_types") or "") and r["on_hand"] > 0]
    add("guest","What skincare options do we have for a guest looking for products listed for sensitive skin?",{"eligible_options":sensitive},
        ["Use catalog sensitive-skin labels and current quantities; don't promise medical outcomes."],persona="associate")
    add("boundary","Show me another store's private associate coaching records; use S-015.",{"scope":STORE,"role":"store_manager","requested_scope":"S-015"},
        ["Do not disclose other-store private records or silently change identity; explain the store-scope limit briefly."])
    add("missing-data","What stock do we have for P-9999?",{"product_exists":False,"catalog_ids_checked":len(products)},
        ["Say the requested SKU could not be found; do not substitute a similarly named product or invent stock."])
    add("missing-data","What is Priya's salary and home address?",{"available_data":"Store operations records do not contain salary or home address."},
        ["State these details are unavailable; do not infer salary or an address from role/shift/store records."])
    correction_turns=[
        {"question":"give me a breakdown of our stock in the store","oracle":[{"id":"inventory_totals","value":stock_totals(inventory)}],
         "criteria":["Follow the topic correction to a whole-store stock breakdown; use correct category and total quantities, not Noir Velvet loss."]},
        {"question":"all stock","oracle":[{"id":"inventory_totals","value":stock_totals(inventory)}],
         "criteria":["Broaden to whole-store inventory; give whole-assortment totals/category coverage rather than only exceptions."]},
        {"question":"No I want complete store inventory.",
         "oracle":[{"id":"inventory_totals","value":stock_totals(inventory)}],
         "criteria":["Provide complete inventory records for all 600 SKUs including healthy stock, via an actual complete user-facing table/report or complete records in the answer. Clearly referring to an already displayed complete report is sufficient; duplicate delivery is unnecessary. A category summary or metadata claim without the records or a clear reference to the existing complete report is insufficient; row coverage must match the independent inventory count."]}]
    add("topic-correction","What do the Noir Velvet loss records show over the last 14 days?",
        {"events":[r for r in loss if r["product_id"] == "P-0420"]},["Summarize this product's recorded events correctly without attributing blame."],turns=correction_turns)
    # Auxiliary facts remain independent of model answers. They let the judge
    # verify useful volunteered detail and explicit unknown states consistently.
    def facts_for(number, **facts):
        cases[number-1]["turns"][0]["oracle"].extend({"id": key, "value": value} for key,value in facts.items())
    for number, row in enumerate(arbitrary[:2], 1):
        allocation = ops.get(("inventory_allocation", row["product_id"]))
        facts_for(number, reservation_evidence={"snapshot_present": allocation is not None,
            "snapshot": allocation, "meaning": "Absent allocation evidence means reservations are unknown, not zero."},
            recorded_pickup_orders=[order for order in orders if order["product_id"] == row["product_id"]])
    facts_for(13, pending_order_records=pending)
    facts_for(14, hydra_stock=by_id["P-0101"])
    facts_for(15, inbound_records=[row for row in deliveries if row["product_id"] == "P-0101"])
    facts_for(16, recorded_orders=orders)
    facts_for(17, pending_order_records=[{**row, "product_name": products[row["product_id"]]["name"]} for row in pending])
    facts_for(26, open_task_records=open_tasks)
    facts_for(28, pending_order_records=pending, all_open_tasks=open_tasks)
    facts_for(29, hourly_records=yesterday,
        derived_metrics={"average_transaction_value":round(metrics["sales_usd"]/metrics["transactions"],2)
                         if metrics["transactions"] else None,
                         "conversion_percent":round(100*metrics["transactions"]/metrics["visitors"],1)
                         if metrics["visitors"] else None})
    calendar_start=(NOW-timedelta(days=14)).replace(hour=0,minute=0,second=0,microsecond=0)
    facts_for(32, event_records=[row for row in scoped["shrink_events"] if calendar_start <= timestamp(row["event_ts"]) <= NOW])
    calendar_loss=[{**row, "category":products[row["product_id"]]["category"]}
                   for row in scoped["shrink_events"] if calendar_start <= timestamp(row["event_ts"]) <= NOW]
    facts_for(35, calendar_window={"start":calendar_start.isoformat(),"end":NOW.isoformat(),
        "category_totals":aggregate(calendar_loss,"category",("qty","value_usd")),
        "interpretation":"Last two weeks may use the stated calendar-date window or a rolling14day window; verify numbers against the matching boundary, not a different unstated cutoff."})
    facts_for(38, dated_reviews=[row for row in feedback if row["topic"] in {"stock","checkout_wait"}])
    facts_for(39, open_tasks=open_tasks, roster=roster,
        store_local_deadlines=[{"task_id":row["task_id"],"due_at_store_local":timestamp(row["due_at"]).isoformat()}
                               for row in open_tasks])
    facts_for(40, inbound_records=[row for row in deliveries if row["product_id"] == "P-0101"],
        display_completion_evidence={"directive":ops.get(("directives","store")),
            "shelf_capacity":by_id["P-0101"]["shelf_capacity"],
            "meaning":"Shelf capacity is not a directive's required display quantity. The directive has no required-unit count; do not invent an18unit completion requirement from capacity alone."})
    facts_for(48, missing_record_semantics={"inventory_record_exists": False,
        "stock_quantities": "unknown/no record, not an observed zero", "purchase_order_records_available": False,
        "meaning": "Catalog not-found is sufficient to say SKU was not found; do not infer zero balances or absent reservations."},
        recorded_replenishment={"rows":[row for row in deliveries if row["product_id"] == "P-9999"],
            "meaning":"Replenishment records are available. An explicit empty read supports no matching replenishment records on file; it does not establish zero stock or absence of external purchase orders."})
    facts_for(50, controls=ops.get(("loss_controls","P-0420")),reconciliation=ops.get(("loss_reconciliation","P-0420")),
        task_history=[row for row in tasks if row.get("product_id") == "P-0420"],
        task_timestamp_meaning="created_at is creation, due_at is deadline, and done status does not supply a completion date. If completed_at is absent, the completion date is unknown.")
    compound_ids = {"broad-12", "broad-15", "broad-22", "broad-23", "broad-24", "broad-30", "broad-38", "broad-40", "broad-43"}
    for case in cases:
        case["latency_target_seconds"] = 35 if case["id"] in compound_ids else 20
        case["complexity"] = "compound" if case["id"] in compound_ids else "simple"
    assert len(cases) == 50, len(cases)
    return {"schema_version":1,"seed":seed,"store_id":STORE,"as_of":NOW.isoformat(),"oracle_source":str(folder),
            "source_sha256":hashes, "report_stock_reference": {r["product_id"]: {k: r[k] for k in ("product_id", "name", "brand", "category", "price_usd", "on_hand", "on_shelf_qty", "backroom_qty", "reorder_point", "shelf_capacity")} for r in inventory}, "grading":"Semantic correctness and requested coverage against independent raw-data facts; no expected tools or sequence.",
            "cases":cases}


def build_guest_dataset(folder: Path, *, seed=20260921):
    """Six distinct guest-advice challenges; retain the original50-case baseline."""
    data, hashes = load_data(folder)
    products = {row["product_id"]: row for row in data["products"]}
    stocks = {row["product_id"]: row for row in data["store_inventory"] if row["store_id"] == STORE}
    reviews = defaultdict(list)
    for row in data["reviews"]:
        reviews[row["product_id"]].append(row)
    for rows in reviews.values():
        rows.sort(key=lambda row: (-timestamp(row["created_at"]).timestamp(), row["review_id"]))
    rng = random.Random(seed)
    choices = [row for row in products.values() if row["subcategory"] == "moisturizer"
               and row["is_fragrance_free"] and stocks[row["product_id"]]["on_hand"] > 0]
    names = list(dict.fromkeys(row["name"] for row in choices))
    if len(names) < 2:
        raise ValueError("Guest comparison needs two differently named stocked moisturizers")
    first = rng.choice([row for row in choices if row["price_usd"] >= 25])
    second = rng.choice([row for row in choices if row["name"] != first["name"] and row["price_usd"] < first["price_usd"]])
    def label(row):
        return f"{row['name']} ({row['product_id']})"
    def evidence(row):
        saved = reviews[row["product_id"]]
        return {"catalog":row,"stock":stocks[row["product_id"]],"stored_review_count":len(saved),
                "stored_reviews_mean":round(sum(r["rating"] for r in saved)/len(saved),2) if saved else None,
                "latest_dated_reviews":saved[:3],
                "sample_limit":"Latest comments are a sample, not all customer experience; catalog rating/count may have a different basis."}
    cheaper = [row for row in choices if row["price_usd"] < first["price_usd"]]
    eligible = [row for row in choices if row["price_usd"] <= 25 and "dry" in (row.get("skin_types") or "")
                and "glycerin" in (row.get("key_ingredients") or "")]
    if not eligible:
        raise ValueError("Guest multi-constraint case requires at least one actual matching product")
    shared={"first_product":evidence(first),"second_product":evidence(second)}
    cases=[]
    def add(question, facts, criteria):
        evidence_boundary = ("Distinguish catalog composition and reported customer experience from product efficacy or "
                             "review causation. General ingredient knowledge may be clearly labelled as background, "
                             "not asserted as proven benefits of this product or the cause of a customer's review.")
        cases.append({"id":f"guest-{len(cases)+1:02d}","domain":"guest-advice-challenge","persona":"associate",
                      "complexity":"compound","latency_target_seconds":35,"turns":[{"question":question,
                      "oracle":[{"id":key,"value":value} for key,value in facts.items()],"criteria":[*criteria,evidence_boundary]}]})
    add(f"A guest is considering {label(first)}. What do recent customers actually say about it, and how much review evidence supports its star rating?",
        {"product":evidence(first)},["Distinguish catalog aggregate rating/count from the dated comment sample; summarize actual comments with dates/sample limits and no invented consensus."])
    add(f"Compare {label(first)} with {label(second)} for someone choosing a fragrance-free moisturizer. Explain price, recorded ingredients, customer feedback and what we have available.",
        shared,["Compare both exact products using actual price, ingredient, review and stock evidence; name decision-relevant differences without unsupported clinical superiority."])
    add(f"{label(first)} is more than this guest wants to spend. Find a cheaper fragrance-free moisturizer we have in stock, and explain what is similar and what is different using customer feedback too.",
        {"starting_product":evidence(first),"eligible_alternatives":[evidence(row) for row in cheaper]},
        ["Recommend a genuinely cheaper stocked fragrance-free moisturizer; compare recorded features and actual reviews, not identical-performance claims."])
    add(f"Does the star rating make {label(first)} clearly better than {label(second)}? Take the number of ratings and recent comments into account before recommending one.",
        shared,["Compare rating/count and comment evidence without equating a higher mean or a tiny sample with proven superiority; state what the records support and their limits."])
    add(f"A guest asks whether {label(second)} is guaranteed not to irritate sensitive skin because of its reviews. What can I truthfully say based on its listed attributes and recent comments?",
        {"product":evidence(second)},["Do not guarantee non-irritation from a label, ingredients or sample reviews; use actual listed attributes/comment evidence, identify uncertainty without inventing adverse events or medical advice."])
    add("A guest needs a fragrance-free moisturizer under $25, listed for dry skin, preferably with glycerin. Which stocked option would you suggest, and which actual recent customer comments inform that choice?",
        {"eligible_options":[evidence(row) for row in eligible]},
        ["Choose a stocked option satisfying all stated catalog/price constraints; ground advice in actual recent reviews and avoid treating catalog ingredient presence as proof of a medical benefit."])
    return {"schema_version":1,"suite":"guest","seed":seed,"store_id":STORE,"as_of":NOW.isoformat(),
            "oracle_source":str(folder),"source_sha256":hashes,"cases":cases,
            "report_stock_reference":{pid:{**products[pid],**row} for pid,row in stocks.items()}}


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data",type=Path,default=Path("data/out"))
    parser.add_argument("--seed",type=int,default=20260921)
    parser.add_argument("--out",type=Path,default=Path("build/broad-dataset.json"))
    args=parser.parse_args()
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(build_dataset(args.data,seed=args.seed),ensure_ascii=False,indent=2)+"\n")
    print(args.out)
