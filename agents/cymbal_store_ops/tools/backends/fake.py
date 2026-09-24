"""In-memory backend over the deterministic generator. Used by unit tests only (no cloud).

The tables come from `data/generate.py::generate_all()` (the same rows `uv run python data/generate.py && bash data/load.sh --env dev` loads into BigQuery),
generated once per process and deep-copied per backend so a test's writes never leak into another.
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import UTC, timedelta
from typing import Any

from agents.cymbal_store_ops import fixtures as F
from agents.cymbal_store_ops.config import REPO_ROOT, EnvConfig
from agents.cymbal_store_ops.tools.data_backend import (
    NOW,
    Row,
    err,
    fold,
    lookback,
    ok,
    parse_ts,
    window,
)
from agents.cymbal_store_ops.tools.sql_guard import SqlGuardError, assert_select_only

_TABLES: dict[str, list[Row]] | None = None


def _tables() -> dict[str, list[Row]]:
    """The generator lives in data/ (not shipped); import it only when a fake is built."""
    global _TABLES
    if _TABLES is None:
        data_dir = str(REPO_ROOT / "data")
        if data_dir not in sys.path:
            sys.path.insert(0, data_dir)
        import generate as G

        _TABLES = G.generate_all()
    return copy.deepcopy(_TABLES)


def _local_day(value: Any) -> str:
    return parse_ts(value).astimezone(NOW.tzinfo).date().isoformat()


class FakeBackend:
    name = "fake"

    def __init__(self, cfg: EnvConfig | None = None, limit: int = 50) -> None:
        t = _tables()
        from agents.cymbal_store_ops.reporting_fixtures import generate_report_tables
        report_tables = generate_report_tables(t)
        self.pos_daily_product_sales = report_tables["pos_daily_product_sales"]
        self.worked_shifts = report_tables["worked_shifts"]
        self.operations = t["operations_context"]
        self.products: list[Row] = t["products"]
        self.reviews: list[Row] = t["reviews"]
        self.stores: list[Row] = t["stores"]
        self.inventory: list[Row] = t["store_inventory"]
        self.associates: list[Row] = t["associates"]
        self.tasks: list[Row] = t["store_tasks"]
        self.orders: list[Row] = t["bopis_orders"]
        self.traffic: list[Row] = t["store_traffic"]
        self.shrink: list[Row] = t["shrink_events"]
        self.feedback: list[Row] = t["guest_feedback"]
        self.coaching: list[Row] = t["coaching_signals"]
        self.replenishment: list[Row] = t["replenishment"]
        self._product = {p["product_id"]: p for p in self.products}
        self._store = {s["store_id"]: s for s in self.stores}
        self.limit = limit
        self.calls: list[tuple[str, dict]] = []

    def get_end_of_day_report_data(self, *, store_id: str, business_date: str, comparison_date: str) -> dict:
        from agents.cymbal_store_ops.tools.backends.reporting import fake_report_data
        return fake_report_data(self, store_id=store_id, business_date=business_date, comparison_date=comparison_date)

    def describe(self) -> dict:
        return {"dialect": "fake", "project_id": "fake", "dataset_id": "cymbal_beauty_fake", "table_prefix": "fake.cymbal_beauty_fake"}

    def healthcheck(self) -> dict:
        return ok([{"ok": True}])

    def _log(self, name: str, **kw: Any) -> None:
        self.calls.append((name, kw))

    def _product_cols(self, product_id: str) -> Row:
        p = self._product[product_id]
        return {"product_name": p["name"], "category": p["category"], "locked_case": p["locked_case"], "price_usd": p["price_usd"]}

    def _inventory_row(self, inv: Row) -> Row:
        s = self._store[inv["store_id"]]
        return {"store_id": inv["store_id"], "store_name": s["name"], "city": s["city"], "state": s["state"],
                "product_id": inv["product_id"], **self._product_cols(inv["product_id"]),
                "on_hand": inv["on_hand"], "on_shelf_qty": inv["on_shelf_qty"], "backroom_qty": inv["backroom_qty"],
                "reorder_point": inv["reorder_point"], "shelf_capacity": inv["shelf_capacity"],
                "bopis_eligible": inv["bopis_eligible"], "updated_at": inv["updated_at"]}

    # ---- catalog and identity ----------------------------------------------------------------------
    def search_products(self, *, query_text, category, max_price, fragrance_free, skin_type, limit) -> dict:
        self._log("search_products", query_text=query_text, category=category, max_price=max_price)
        q = fold(query_text or "")
        rows = []
        for p in self.products:
            if category and p["category"] != category:
                continue
            if max_price is not None and p["price_usd"] > max_price:
                continue
            if fragrance_free is not None and p["is_fragrance_free"] != fragrance_free:
                continue
            if skin_type and (not p["skin_types"] or skin_type not in p["skin_types"]):
                continue
            if q and not any(q in fold(str(p[k])) for k in ("name", "subcategory", "key_ingredients", "brand", "description")):
                continue
            rows.append({k: p[k] for k in ("product_id", "brand", "name", "category", "subcategory", "price_usd",
                                           "is_fragrance_free", "locked_case", "skin_types", "key_ingredients", "rating_avg", "rating_count")})
        rows.sort(key=lambda r: (-(r["rating_avg"] or 0), r["price_usd"]))
        return ok(rows[:limit], limit=limit, total_matching=len(rows))

    def get_product_details(self, product_id: str) -> dict:
        self._log("get_product_details", product_id=product_id)
        p = self._product.get(product_id)
        if not p:
            return err(f"product {product_id} not found")
        reviews = [r for r in self.reviews if r["product_id"] == product_id]
        reviews.sort(key=lambda r: r["review_id"])
        reviews.sort(key=lambda r: parse_ts(r["created_at"]), reverse=True)
        keys = ("review_id", "rating", "title", "body", "skin_type", "created_at")
        return ok([{**p, "top_reviews": [{k: r[k] for k in keys} for r in reviews[:3]],
                    "available_review_count": len(reviews),
                    "review_sample_basis": "latest 3, not a representative sample"}])

    def list_stores(self, *, city: str | None) -> dict:
        self._log("list_stores", city=city)
        rows = [{k: s[k] for k in ("store_id", "name", "city", "state", "opens", "closes")}
                for s in self.stores if city is None or s["city"].lower() == city.lower()]
        return ok(rows)

    def list_associates(self, *, store_id: str) -> dict:
        self._log("list_associates", store_id=store_id)
        rows = [{k: a[k] for k in ("associate_id", "first_name", "role", "store_id")}
                for a in self.associates if a["store_id"] == store_id]
        return ok(sorted(rows, key=lambda r: r["associate_id"]))

    def get_associate(self, associate_id: str) -> dict:
        self._log("get_associate", associate_id=associate_id)
        a = next((a for a in self.associates if a["associate_id"] == associate_id), None)
        if not a:
            return err(f"associate {associate_id} not found", code="not_found")
        return ok([{**a, "store_name": self._store[a["store_id"]]["name"]}])

    # ---- inventory excellence -----------------------------------------------------------------------
    def _inventory_listing(self, store_id: str) -> list[Row]:
        rows = []
        for stock in self.inventory:
            if stock["store_id"] != store_id:
                continue
            product = self._product[stock["product_id"]]
            rows.append({"product_id": stock["product_id"], "product_name": product["name"],
                         "category": product["category"], "brand": product["brand"],
                         "price_usd": product["price_usd"],
                         **{key: stock[key] for key in ("on_hand", "on_shelf_qty", "backroom_qty", "reorder_point")}})
        return rows

    def get_store_inventory_summary(self, *, store_id: str, category: str = "") -> dict:
        from agents.cymbal_store_ops.tools.inventory_summary import summary_result
        self._log("get_store_inventory_summary", store_id=store_id, category=category)
        groups: dict[str, list[Row]] = {}
        for row in self._inventory_listing(store_id):
            groups.setdefault(row["category"], []).append(row)
        rows = []
        for name, stocks in sorted(groups.items()):
            rows.append({"category": name, "inventory_row_count": len(stocks),
                         "sku_count": len({r["product_id"] for r in stocks}),
                         "stocked_sku_count": len({r["product_id"] for r in stocks if r["on_hand"] > 0}),
                         "on_hand_units": sum(r["on_hand"] for r in stocks),
                         "on_shelf_units": sum(r["on_shelf_qty"] for r in stocks),
                         "backroom_units": sum(r["backroom_qty"] for r in stocks),
                         "empty_shelf_sku_count": len({r["product_id"] for r in stocks if r["on_shelf_qty"] == 0 and r["on_hand"] > 0}),
                         "out_of_stock_sku_count": len({r["product_id"] for r in stocks if r["on_hand"] == 0}),
                         "low_stock_sku_count": len({r["product_id"] for r in stocks if r["on_hand"] < r["reorder_point"]})})
        return summary_result(rows, store_id=store_id, category=category)

    def list_store_inventory(self, *, store_id: str, category: str = "", query_text: str = "",
                             availability: str = "all", limit: int = 25, offset: int = 0) -> dict:
        from agents.cymbal_store_ops.tools.inventory_summary import page_result, validate_page
        self._log("list_store_inventory", store_id=store_id, category=category, query_text=query_text,
                  availability=availability, limit=limit, offset=offset)
        if error := validate_page(availability, limit, offset):
            return error
        category, query = category.strip().casefold(), fold(query_text.strip())
        source = self._inventory_listing(store_id)
        categories = sorted({row["category"] for row in source})
        matches = []
        for row in source:
            if category and row["category"] != category:
                continue
            if query and not any(query in fold(str(row[key])) for key in ("product_id", "product_name", "brand")):
                continue
            include = {"all": True, "in_stock": row["on_hand"] > 0, "out_of_stock": row["on_hand"] == 0,
                       "empty_shelf": row["on_shelf_qty"] == 0 and row["on_hand"] > 0,
                       "low_stock": row["on_hand"] < row["reorder_point"]}[availability]
            if include:
                matches.append(row)
        matches.sort(key=lambda row: row["product_id"])
        return page_result(matches[offset:offset + limit], store_id=store_id, category=category,
                           query_text=query_text.strip(), availability=availability, limit=limit, offset=offset,
                           total_matching=len(matches), available_categories=categories)

    def get_osa_exceptions(self, *, store_id: str, limit: int) -> dict:
        self._log("get_osa_exceptions", store_id=store_id, limit=limit)
        if store_id not in self._store:
            return err(f"store {store_id} not found", code="not_found")
        rows = []
        for i in self.inventory:
            if i["store_id"] != store_id:
                continue
            shelf_empty = i["on_shelf_qty"] == 0 and i["on_hand"] > 0
            below = i["on_hand"] < i["reorder_point"]
            if shelf_empty or below:
                rows.append({**self._inventory_row(i), "exception_type": "shelf_empty" if shelf_empty else "below_reorder_point",
                             "shortfall": i["reorder_point"] - i["on_hand"]})
        rows.sort(key=lambda r: (r["exception_type"] != "shelf_empty", -r["shortfall"], -r["backroom_qty"], r["product_id"]))
        return ok(rows[:limit], limit=limit)

    def _match_products(self, product_name: str) -> list[Row]:
        needle = fold(product_name)
        return [p for p in self.products if needle in fold(p["name"]) or needle == p["product_id"].lower()]

    def check_store_stock(self, *, product_name: str, store_id: str) -> dict:
        self._log("check_store_stock", product_name=product_name, store_id=store_id)
        if store_id not in self._store:
            return err(f"store {store_id} not found", code="not_found")
        prods = self._match_products(product_name)
        if not prods:
            return err(f"no product matches {product_name!r}")
        wanted = {p["product_id"] for p in prods[:5]}
        rows = [self._inventory_row(i) for i in self.inventory if i["store_id"] == store_id and i["product_id"] in wanted]
        return ok(rows)

    def find_nearby_stock(self, *, product_name: str, store_id: str, limit: int) -> dict:
        self._log("find_nearby_stock", product_name=product_name, store_id=store_id, limit=limit)
        home = self._store.get(store_id)
        if not home:
            return err(f"store {store_id} not found", code="not_found")
        prods = self._match_products(product_name)
        if not prods:
            return err(f"no product matches {product_name!r}")
        wanted = {p["product_id"] for p in prods[:5]}
        same_state = {s["store_id"] for s in self.stores if s["state"] == home["state"] and s["store_id"] != store_id}
        rows = [self._inventory_row(i) for i in self.inventory
                if i["store_id"] in same_state and i["product_id"] in wanted and i["on_hand"] > 0]
        rows.sort(key=lambda r: (-r["on_hand"], r["store_id"]))
        return ok(rows[:limit], limit=limit)

    def get_bopis_demand(self, *, store_id: str, product_id: str | None, hours: int) -> dict:
        self._log("get_bopis_demand", store_id=store_id, product_id=product_id, hours=hours)
        _, until = window(hours=hours)
        rows = [{**o, **self._product_cols(o["product_id"])} for o in self.orders
                if o["store_id"] == store_id and o["status"] == "pending" and parse_ts(o["promised_at"]) <= until
                and (product_id is None or o["product_id"] == product_id)]
        rows.sort(key=lambda r: (r["promised_at"], r["order_id"]))
        return ok(rows[:self.limit], limit=self.limit, pending_count=len(rows), window_end=until.isoformat())

    def get_replenishment_status(self, *, store_id: str, product_id: str | None) -> dict:
        self._log("get_replenishment_status", store_id=store_id, product_id=product_id)
        rows = [{**r, **self._product_cols(r["product_id"])} for r in self.replenishment
                if r["store_id"] == store_id and (product_id is None or r["product_id"] == product_id)]
        rows.sort(key=lambda r: (r["expected_at"], r["product_id"]))
        return ok(rows[:self.limit], limit=self.limit)

    def _task_rows(self, tasks: list[Row]) -> list[Row]:
        return [{**t, "product_name": self._product[t["product_id"]]["name"] if t["product_id"] else None} for t in tasks]

    def get_task_status(self, *, store_id: str, product_id: str | None, status: str | None) -> dict:
        self._log("get_task_status", store_id=store_id, product_id=product_id, status=status)
        rows = [t for t in self.tasks if t["store_id"] == store_id and (product_id is None or t["product_id"] == product_id)
                and (status is None or t["status"] == status)]
        rows.sort(key=lambda t: (t["due_at"], t["task_id"]))
        return ok(self._task_rows(rows[:self.limit]), limit=self.limit)

    # ---- associate orchestration --------------------------------------------------------------------
    def get_shift_roster(self, *, store_id: str, at_iso: str) -> dict:
        self._log("get_shift_roster", store_id=store_id, at_iso=at_iso)
        if store_id not in self._store:
            return err(f"store {store_id} not found", code="not_found")
        at = parse_ts(at_iso)
        rows = [{k: a[k] for k in ("associate_id", "first_name", "role", "skills", "shift_start", "shift_end", "current_task")}
                for a in self.associates if a["store_id"] == store_id and parse_ts(a["shift_start"]) <= at < parse_ts(a["shift_end"])]
        for row in rows:
            row["assigned_tasks"] = [dict(t) for t in self.tasks if t["store_id"] == store_id
                                     and t.get("assignee_id") == row["associate_id"] and t["status"] == "open"]
        rows.sort(key=lambda r: (r["shift_end"], r["associate_id"]))
        return ok(rows)

    def get_traffic_and_backlog(self, *, store_id: str, hours: int) -> dict:
        self._log("get_traffic_and_backlog", store_id=store_id, hours=hours)
        start, until = window(hours=hours)
        rows = [{k: t[k] for k in ("ts_hour", "visitors", "transactions", "sales_usd")} for t in self.traffic
                if t["store_id"] == store_id and start <= parse_ts(t["ts_hour"]) < until]
        rows.sort(key=lambda r: r["ts_hour"])
        promised = sorted(o["promised_at"] for o in self.orders
                          if o["store_id"] == store_id and o["status"] == "pending" and parse_ts(o["promised_at"]) <= until)
        return ok(rows, pending_bopis=len(promised), earliest_promise=promised[0] if promised else None,
                  latest_promise=promised[-1] if promised else None, window_start=start.isoformat(), window_end=until.isoformat())

    # ---- loss prevention ----------------------------------------------------------------------------
    def get_shrink_signals(self, *, store_id: str, product_id: str | None, days: int) -> dict:
        self._log("get_shrink_signals", store_id=store_id, product_id=product_id, days=days)
        since, until = lookback(days)
        groups: dict[tuple[str, str], Row] = {}
        for e in self.shrink:
            if e["store_id"] != store_id or (product_id is not None and e["product_id"] != product_id):
                continue
            if not (since <= parse_ts(e["event_ts"]) <= until):
                continue
            g = groups.setdefault((e["product_id"], e["event_type"]), {
                "product_id": e["product_id"], **self._product_cols(e["product_id"]), "event_type": e["event_type"],
                "events": 0, "qty": 0, "value_usd": 0.0, "first_event_ts": e["event_ts"], "last_event_ts": e["event_ts"]})
            g["events"] += 1
            g["qty"] += e["qty"]
            g["value_usd"] = round(g["value_usd"] + e["value_usd"], 2)
            g["first_event_ts"] = min(g["first_event_ts"], e["event_ts"])
            g["last_event_ts"] = max(g["last_event_ts"], e["event_ts"])
        rows = sorted(groups.values(), key=lambda r: (-r["value_usd"], r["product_id"], r["event_type"]))
        return ok(rows[:self.limit], limit=self.limit, complete=len(rows) < self.limit, window_start=since.isoformat(), window_end=until.isoformat())

    def get_sales_pattern(self, *, store_id: str, product_id: str | None, days: int) -> dict:
        self._log("get_sales_pattern", store_id=store_id, product_id=product_id, days=days)
        start, until = window(days=days)
        by_day: dict[str, Row] = {}
        for t in self.traffic:
            if t["store_id"] != store_id or not (start <= parse_ts(t["ts_hour"]) < until):
                continue
            d = by_day.setdefault(_local_day(t["ts_hour"]), {"day": _local_day(t["ts_hour"]), "visitors": 0, "transactions": 0, "sales_usd": 0.0})
            d["visitors"] += t["visitors"]
            d["transactions"] += t["transactions"]
            d["sales_usd"] = round(d["sales_usd"] + t["sales_usd"], 2)
        rows = [by_day[k] for k in sorted(by_day)]
        return ok(rows, product_id=product_id, granularity="store-level daily totals")

    def get_task_history(self, *, store_id: str, product_id: str | None, days: int) -> dict:
        self._log("get_task_history", store_id=store_id, product_id=product_id, days=days)
        since, _ = lookback(days)
        rows = [t for t in self.tasks if t["store_id"] == store_id and (product_id is None or t["product_id"] == product_id)
                and parse_ts(t["created_at"]) >= since]
        rows.sort(key=lambda t: (t["created_at"], t["task_id"]), reverse=True)
        return ok(self._task_rows(rows[:self.limit]), limit=self.limit)

    # ---- daily briefing and associate development ---------------------------------------------------
    def get_guest_feedback(self, *, store_id: str, days: int) -> dict:
        self._log("get_guest_feedback", store_id=store_id, days=days)
        since, _ = lookback(days)
        rows = [f for f in self.feedback if f["store_id"] == store_id and parse_ts(f["submitted_at"]) >= since]
        rows.sort(key=lambda f: (f["submitted_at"], f["feedback_id"]), reverse=True)
        return ok(rows[:self.limit], limit=self.limit)

    def get_coaching_signals(self, *, associate_id: str, period: str | None) -> dict:
        self._log("get_coaching_signals", associate_id=associate_id, period=period)
        a = next((a for a in self.associates if a["associate_id"] == associate_id), None)
        if not a:
            return err(f"associate {associate_id} not found", code="not_found")
        rows = [{**c, "first_name": a["first_name"], "role": a["role"], "store_id": a["store_id"]} for c in self.coaching
                if c["associate_id"] == associate_id and (period is None or c["period"] == period)]
        rows.sort(key=lambda c: (c["period"], c["metric"]))
        return ok(rows, associate={k: a[k] for k in ("associate_id", "first_name", "role", "store_id", "skills")})

    def get_assigned_tasks(self, *, store_id, associate_id) -> dict:
        return ok(self._task_rows([t for t in self.tasks if t["store_id"] == store_id and t["assignee_id"] == associate_id]))

    def complete_assigned_task(self, *, store_id, associate_id, task_id, completion_note) -> dict:
        task = next((t for t in self.tasks if t["store_id"] == store_id and t["assignee_id"] == associate_id and t["task_id"] == task_id), None)
        if not task or task["status"] not in {"open", "done"}:
            return err("Task assignment or status changed; refresh your work.", code="conflict")
        done = task["status"] == "done"
        if not done:
            task.update(status="done", note=task["note"] + " | Completion: " + completion_note)
        return ok(self._task_rows([task]), already_completed=done)

    def report_assigned_task_blocker(self, *, store_id, associate_id, task_id, blocker) -> dict:
        task = next((t for t in self.tasks if t["store_id"] == store_id and t["assignee_id"] == associate_id and t["task_id"] == task_id), None)
        if not task or task["status"] != "open":
            return err("Task assignment or status changed; refresh your work.", code="conflict")
        marker = " | Blocker: " + blocker + " |"
        already_reported = marker in task["note"]
        if not already_reported:
            task["note"] += marker
        return ok(self._task_rows([task]), already_reported=already_reported)

    def get_operations_context(self, *, store_id, system, subject_id) -> dict:
        self._log("get_operations_context", store_id=store_id, system=system, subject_id=subject_id)
        return ok([{**r, "payload": json.loads(r["payload"])} for r in self.operations
                   if r["store_id"] == store_id and r["system"] == system and r["subject_id"] == subject_id])

    # ---- the only writes ----------------------------------------------------------------------------
    def create_store_task(self, *, store_id, task_type, product_id, assignee_id, note, task_key, due_at=None) -> dict:
        self._log("create_store_task", store_id=store_id, task_type=task_type, product_id=product_id, assignee_id=assignee_id, task_key=task_key)
        existing = next((t for t in self.tasks if t["task_key"] == task_key), None)
        if existing:
            return ok(self._task_rows([existing]), already_created=True)
        if task_type not in F.TASK_TYPES:
            return err(f"task_type {task_type!r} is not one of {F.TASK_TYPES}")
        if product_id and product_id not in self._product:
            return err(f"product {product_id} not found", code="not_found")
        if assignee_id and not any(a["associate_id"] == assignee_id and a["store_id"] == store_id for a in self.associates):
            return err(f"{assignee_id} is not an associate at {store_id}", code="not_found")
        row = {"task_id": f"T-{task_key[:8].upper()}", "store_id": store_id, "task_type": task_type,
               "product_id": product_id or None, "assignee_id": assignee_id or None, "status": "open", "source": "agent",
               "created_at": NOW.astimezone(UTC).isoformat(), "due_at": due_at or (NOW + timedelta(hours=4)).astimezone(UTC).isoformat(),
               "note": note, "task_key": task_key, "delegation_key": None}
        self.tasks.append(row)
        return ok(self._task_rows([row]), already_created=False)

    def delegate_task(self, *, store_id, task_id, assignee_id, task_key) -> dict:
        self._log("delegate_task", store_id=store_id, task_id=task_id, assignee_id=assignee_id, task_key=task_key)
        task = next((t for t in self.tasks if t["task_id"] == task_id and t["store_id"] == store_id), None)
        if not task:
            return err(f"task {task_id} not found at {store_id}", code="not_found")
        if not any(a["associate_id"] == assignee_id and a["store_id"] == store_id for a in self.associates):
            return err(f"{assignee_id} is not an associate at {store_id}", code="not_found")
        if task["delegation_key"] == task_key and task["assignee_id"] == assignee_id:
            return ok(self._task_rows([task]), already_delegated=True)
        if task["status"] != "open":
            return err(f"task {task_id} is {task['status']}; only open tasks can be delegated", code="conflict")
        task["assignee_id"], task["delegation_key"] = assignee_id, task_key
        return ok(self._task_rows([task]), already_delegated=False)

    # ---- raw SQL extension --------------------------------------------------------------------------
    def list_table_ids(self) -> dict:
        return ok([{"table_id": t} for t in F.EXPECTED_ROW_COUNTS])

    def get_table_info(self, table_id: str) -> dict:
        path = REPO_ROOT / "data" / "schemas" / f"{table_id}.json"
        if not path.exists():
            return err(f"table {table_id} not found")
        return ok([{"tableReference": {"tableId": table_id}, "schema": {"fields": json.loads(path.read_text())}}])

    def execute_sql(self, query: str) -> dict:
        try:
            assert_select_only(query, (self.describe()["table_prefix"],))
        except SqlGuardError as e:
            return err(f"Read-only mode only supports SELECT statements: {e}")
        return err("FakeBackend does not execute SQL")

    def sql_tools(self) -> list:
        return []
