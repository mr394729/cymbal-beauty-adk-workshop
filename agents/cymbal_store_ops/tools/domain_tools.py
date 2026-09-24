"""ADK tools for the store-operations agents. Thin, deterministic wrappers over the DataBackend contract.

Design rules (taught in module 2):
  * the store in scope comes from session state (`user:store_id`, seeded by `identify_demo_user`); a tool
    only accepts an explicit `store_id` so a district manager can look at another store, and the
    store-scope callback checks that argument against the role;
  * every tool returns the shared envelope, so the model sees one shape on every backend;
  * the recommendation rules live here as plain code (OSA, coverage, shrink), so the evals can assert
    them and a prompt change cannot move them;
  * STORE_OPS_FAULT injects a known-wrong answer for the evaluation lab — deterministic, not a prompt edit.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from typing import Any, Literal

from google.adk.tools import ToolContext

from agents.cymbal_store_ops import fixtures as F
from agents.cymbal_store_ops.config import load_env_config
from agents.cymbal_store_ops.tools.data_backend import (
    NOW,
    Row,
    err,
    fold,
    make_backend,
    ok,
    parse_ts,
)

SHRINK_INVESTIGATE_EVENTS = 5       # investigate when a product has at least this many events in the window
SHRINK_INVESTIGATE_VALUE_USD = 250.0  # or at least this much value lost
DEFAULT_COVERAGE_FOCUS = "bopis"
STATE_USER_ID, STATE_STORE_ID, STATE_ROLE, STATE_FIRST_NAME = "user:user_id", "user:store_id", "user:role", "user:first_name"
NO_STORE_IN_SCOPE = "no store is in scope for this session: call identify_demo_user first (production: the signed-in device sets it)"


# ---- helpers ------------------------------------------------------------------------------------------
def _state(tool_context: ToolContext | None) -> dict:
    return tool_context.state if tool_context is not None else {}


def _scope(store_id: str, tool_context: ToolContext | None) -> tuple[str | None, dict | None]:
    """The store a tool works on: the explicit argument if given, else the session's store, else an error."""
    sid = store_id or _state(tool_context).get(STATE_STORE_ID) or ""
    return (sid, None) if sid else (None, err(NO_STORE_IN_SCOPE))


def _manager_scope(store_id: str, tool_context: ToolContext | None) -> tuple[str | None, dict | None]:
    """Enforce manager identity and store scope even for direct/internal tool calls."""
    state = _state(tool_context)
    home, role = state.get(STATE_STORE_ID), state.get(STATE_ROLE)
    if not home or not state.get(STATE_USER_ID) or role not in {"store_manager", "district_manager"}:
        return None, err("This read requires a signed-in manager.", code="forbidden")
    if store_id and store_id != home and role != "district_manager":
        return None, err("This session can read only its signed-in store.", code="forbidden")
    return store_id or home, None


PRODUCT_ID = re.compile(r"P-\d{3,6}")


def _bad_product_id(product_id: str) -> dict | None:
    """A product filter must be an id: a name here silently matches nothing and reads as 'no data'."""
    if product_id and not PRODUCT_ID.fullmatch(product_id.strip()):
        return err(f"product_id {product_id!r} is not a product id like P-0101. Look the id up by name first "
                   "(search_products, or check_store_stock where you have it), or leave product_id empty for the whole store.",
                   code="invalid_argument")
    return None


def _fault() -> str:
    return load_env_config().fault


def _stale_backlog(result: dict, rows_key: str | None, count_key: str) -> dict:
    """STORE_OPS_FAULT=stale_backlog: the BOPIS sync looks three hours stale, so the agent sees no pending orders
    at all (the plan then misses the coverage gap and the eval catches it)."""
    result[count_key] = 0
    if rows_key:
        result[rows_key] = []
    result["fault_injected"] = "stale_backlog"
    return result


def _stale_stock(result: dict) -> dict:
    """STORE_OPS_FAULT=stale_stock: the inventory feed is stale for the hero product; it reports five more units
    in the backroom (and therefore on hand) than the store really has."""
    for row in result.get("rows", []):
        if row.get("product_id") == F.HERO_PRODUCT_ID:
            row["on_hand"] = int(row["on_hand"]) + 5
            if "backroom_qty" in row:
                row["backroom_qty"] = int(row["backroom_qty"]) + 5
    result["fault_injected"] = "stale_stock"
    return result


# ---- the deterministic rules (pure functions; unit-tested directly) -----------------------------------
def osa_recommendation(row: Row, replenishment: list[Row]) -> dict:
    """Inventory-excellence rule for one store/product position.

    backroom_check  when nothing is on the shelf but units sit in the backroom;
    replenish       when on_hand is below the reorder point and no replenishment is in transit;
    cycle_count     when the system says units exist but neither the shelf nor the backroom has them;
    escalate        when the position is an exception and none of the above applies;
    none            when the position is not an OSA exception at all.
    """
    on_hand, shelf, backroom, rp = int(row["on_hand"]), int(row["on_shelf_qty"]), int(row["backroom_qty"]), int(row["reorder_point"])
    in_transit = any(r["status"] == "in_transit" and r["product_id"] == row["product_id"] for r in replenishment)
    delayed = any(r["status"] == "delayed" and r["product_id"] == row["product_id"] for r in replenishment)
    actions: list[str] = []
    reasons: list[str] = []
    if shelf == 0 and backroom > 0:
        actions.append("backroom_check")
        reasons.append(f"nothing on the shelf while {backroom} unit(s) sit in the backroom")
    if on_hand < rp and not in_transit:
        actions.append("replenish")
        inbound = "its inbound shipment is delayed, not in transit" if delayed else "no replenishment is in transit"
        reasons.append(f"on_hand {on_hand} is below the reorder point {rp} and {inbound}")
    if on_hand > 0 and shelf == 0 and backroom == 0:
        actions.append("cycle_count")
        reasons.append(f"the system counts {on_hand} unit(s) but neither the shelf nor the backroom has any")
    is_exception = (shelf == 0 and on_hand > 0) or on_hand < rp
    if is_exception and not actions:
        actions.append("escalate")
        reasons.append("OSA exception with replenishment already in transit; nothing the store can do locally")
    return {"is_osa_exception": is_exception, "recommendation": actions[0] if actions else "none",
            "recommended_actions": actions, "replenishment_in_transit": in_transit, "replenishment_delayed": delayed,
            "reason": "; ".join(reasons) or "not an OSA exception"}


def coverage_candidates(roster: list[Row], *, focus: str, window_end: datetime) -> list[Row]:
    """Associate-orchestration rule: free associates (no current task) with the focus skill, the ones who
    cover the whole window first, then by earliest shift end (use the shortest shift that still covers it)."""
    cands = []
    for r in roster:
        if r.get("role") != "associate" or r.get("current_task") or r.get("assigned_tasks") or focus not in (r.get("skills") or []):
            continue
        cands.append({**r, "covers_window": parse_ts(r["shift_end"]) >= window_end})
    cands.sort(key=lambda r: (not r["covers_window"], parse_ts(r["shift_end"]), r["associate_id"]))
    return cands


def shrink_recommendation(events: int, value_usd: float) -> str:
    """Loss-prevention rule: investigate above either threshold, otherwise keep monitoring."""
    return "investigate" if events >= SHRINK_INVESTIGATE_EVENTS or value_usd >= SHRINK_INVESTIGATE_VALUE_USD else "monitor"


# ---- identity and clock -------------------------------------------------------------------------------
def identify_demo_user(user_id: str, tool_context: ToolContext) -> dict:
    """DEMO ONLY: choose which Cymbal Beauty employee this session acts as, by associate id (U-M014, A-1004, A-1001).

    Seeds user:user_id, user:store_id, user:role (associate | store_manager | district_manager) and user:first_name.
    In production the identity comes from the signed-in device, never from the conversation.
    """
    result = make_backend().get_associate(user_id.strip())
    if result.get("status") != "SUCCESS":
        return err(f"{user_id!r} is not a demo identity; use an associate id such as {F.HERO_MANAGER_ID} (store manager), "
                   f"{F.HERO_ASSOCIATE_ID} (associate) or {F.HERO_DISTRICT_MANAGER_ID} (district manager)")
    a = result["rows"][0]
    tool_context.state[STATE_USER_ID] = a["associate_id"]
    tool_context.state[STATE_STORE_ID] = a["store_id"]
    tool_context.state[STATE_ROLE] = a["role"]
    tool_context.state[STATE_FIRST_NAME] = a["first_name"]
    return ok([{"user_id": a["associate_id"], "first_name": a["first_name"], "role": a["role"], "store_id": a["store_id"],
                "store_name": a.get("store_name"), "note": "demo identity set for this session"}])


def workshop_clock() -> dict:
    """The workshop's frozen 'now' so 'this morning' and 'until 11' resolve the same way for everyone."""
    return ok([{"now": F.FIXTURE_NOW_ISO, "timezone": F.FIXTURE_TIMEZONE, "today": F.FIXTURE_NOW_ISO[:10], "weekday": "Saturday"}])


# ---- catalog -------------------------------------------------------------------------------------------
def search_products(query_text: str = "", category: str = "", max_price: float = 0.0,
                    fragrance_free: bool | None = None, skin_type: str = "", limit: int = 8) -> dict:
    """Search the Cymbal Beauty catalog.

    Args:
        query_text: free text matched against name, subcategory, ingredients, brand, description (e.g. "moisturizer").
        category: one of skincare, haircare, bath, fragrance, makeup. Empty = any.
        max_price: maximum price in USD. 0 = no limit.
        fragrance_free: True to return only fragrance-free products; omit for any.
        skin_type: one of dry, oily, combination, sensitive, normal. Empty = any.
        limit: maximum rows (1-20).
    The envelope's `total_matching` is how many catalog products match, whatever the page size.
    Returns:
        {"status": "SUCCESS", "rows": [...]} sorted by rating, or {"status": "ERROR", "error_details": ...}.
    """
    return make_backend().search_products(
        query_text=query_text or None, category=category or None, max_price=max_price or None,
        fragrance_free=fragrance_free, skin_type=skin_type or None, limit=max(1, min(int(limit), 20)))


def get_product_details(product_id: str) -> dict:
    """Read one exact product's catalog attributes, description, rating/count and three latest dated reviews.

    Reviews include source ID, rating, text and reviewer skin type. These individual experiences are
    a recent sample, not a population-wide theme or proof of suitability. available_review_count
    states the full number of stored reviews; review_sample_basis describes selection. Product IDs
    use the P- prefix. This catalog read does not report current store stock or change any records.
    """
    return make_backend().get_product_details(product_id)


# ---- inventory excellence (sheet row 3) -----------------------------------------------------------------
def get_osa_exceptions(limit: int = 20, store_id: str = "", tool_context: ToolContext | None = None) -> dict:
    """List the store's on-shelf-availability exceptions with a recommendation for each.

    An exception is a product with nothing on the shelf while units are on hand, or on_hand below the reorder
    point. Rows carry on_hand / on_shelf_qty / backroom_qty / reorder_point / shelf_capacity and a
    `recommendation` (backroom_check | replenish | cycle_count | escalate), worst first.

    Args:
        limit: maximum rows (1-50).
        store_id: leave empty for the signed-in user's store; district managers may name another store.
    """
    sid, error = _scope(store_id, tool_context)
    if error:
        return error
    backend = make_backend()
    result = backend.get_osa_exceptions(store_id=sid, limit=max(1, min(int(limit), 50)))
    if result.get("status") != "SUCCESS":
        return result
    if _fault() == "stale_stock":
        _stale_stock(result)
    repl = backend.get_replenishment_status(store_id=sid, product_id=None)
    repl_rows = repl.get("rows", []) if repl.get("status") == "SUCCESS" else []
    for row in result["rows"]:
        row.update(osa_recommendation(row, repl_rows))
    return result


def check_store_stock(product_name: str, city: str = "", store_id: str = "", tool_context: ToolContext | None = None) -> dict:
    """Stock position of one product: on_hand, on_shelf_qty, backroom_qty, reorder_point, shelf_capacity, BOPIS
    eligibility, and the OSA recommendation (backroom_check | replenish | cycle_count | escalate | none).

    Args:
        product_name: product name or a distinctive part of it (e.g. "Hydra Cream"), or a product id.
        city: look at the Cymbal Beauty store(s) in this city instead of the signed-in store (e.g. "Naperville").
        store_id: look at this store instead of the signed-in store (district managers).
    """
    backend = make_backend()
    if city:
        stores = backend.list_stores(city=city)
        if stores.get("status") != "SUCCESS":
            return stores
        if not stores["rows"]:
            return err(f"no Cymbal Beauty store in {city!r}")
        store_ids = [s["store_id"] for s in stores["rows"]]
    else:
        sid, error = _scope(store_id, tool_context)
        if error:
            return error
        store_ids = [sid]
    rows: list[Row] = []
    for sid in store_ids:
        repl = backend.get_replenishment_status(store_id=sid, product_id=None)
        repl_rows = repl.get("rows", []) if repl.get("status") == "SUCCESS" else []
        result = backend.check_store_stock(product_name=product_name, store_id=sid)
        if result.get("status") != "SUCCESS":
            return result
        for row in result["rows"]:
            rows.append({**row, **osa_recommendation(row, repl_rows)})
    out = ok(rows)
    if _fault() == "stale_stock":
        _stale_stock(out)
        for row in out["rows"]:      # the rule runs on what the agent sees: a stale count changes the plan
            if row.get("product_id") == F.HERO_PRODUCT_ID:
                row.update(osa_recommendation(row, []))
    return out


def find_nearby_stock(product_name: str, limit: int = 5, store_id: str = "", tool_context: ToolContext | None = None) -> dict:
    """Other Cymbal Beauty stores in the same state that have the product on hand (for a transfer or a guest referral).

    Args:
        product_name: product name or a distinctive part of it, or a product id.
        limit: maximum rows (1-20).
        store_id: the home store; leave empty for the signed-in user's store.
    """
    sid, error = _scope(store_id, tool_context)
    if error:
        return error
    return make_backend().find_nearby_stock(product_name=product_name, store_id=sid, limit=max(1, min(int(limit), 20)))


def _summarise_bopis(result: dict) -> None:
    """Count orders and units per product here, in code, instead of asking a model to do the arithmetic.

    An order is a row; its `qty` is units. Asked to do this itself a model reports one as the other: on
    2026-09-20 a start-of-day briefing said "4 pending BOPIS orders" for the hero product, which has 3 orders
    totalling 4 units, and the consultant said "3 orders totalling 4 units" thirty seconds later. Both numbers
    were in the data; only the labels moved. `by_product` is derived from the rows the backend returned, and
    those are capped, so `by_product_complete` says whether every pending order is inside that count.
    """
    rows = result.get("rows") or []
    per: dict[str, dict[str, Any]] = {}
    promises: dict[str, list[datetime]] = {}
    for r in rows:
        pid = str(r.get("product_id") or "")
        entry = per.setdefault(pid, {"product_id": pid, "product_name": r.get("product_name"), "orders": 0, "units": 0})
        entry["orders"] += 1
        entry["units"] += int(r.get("qty") or 0)
        if r.get("promised_at"):
            promises.setdefault(pid, []).append(parse_ts(r["promised_at"]))
    for pid, entry in per.items():
        times = promises.get(pid, [])
        entry["earliest_promise"] = min(times).isoformat() if times else None
        entry["latest_promise"] = max(times).isoformat() if times else None
        entry["promise_times_complete"] = len(times) == entry["orders"]
    result["by_product"] = sorted(per.values(), key=lambda e: (-e["orders"], e["product_id"]))
    result["units_total"] = sum(e["units"] for e in result["by_product"])
    result["by_product_complete"] = result.get("pending_count") == len(rows)


def get_bopis_demand(product_id: str = "", hours: int = 4, store_id: str = "", tool_context: ToolContext | None = None) -> dict:
    """Pending buy-online-pick-up-in-store orders promised within the next `hours` (overdue ones included).

    Returns the orders (rows), `pending_count` (orders), and `by_product` with `orders` and `units` counted per
    product, plus each product's earliest/latest pickup promise among the returned rows.
    `by_product_complete` and `promise_times_complete` indicate whether counts and times are complete.
    Use the returned quantities and ranges: an order is not a unit and the first deadline is not every deadline.
    Filter to one product with product_id (e.g. P-0101).

    Args:
        product_id: optional product id filter.
        hours: window length from the workshop clock (1-24).
        store_id: leave empty for the signed-in user's store.
    """
    sid, error = _scope(store_id, tool_context)
    if error:
        return error
    if bad := _bad_product_id(product_id):
        return bad
    result = make_backend().get_bopis_demand(store_id=sid, product_id=product_id or None, hours=max(1, min(int(hours), 24)))
    if result.get("status") == "SUCCESS":
        if _fault() == "stale_backlog":
            _stale_backlog(result, "rows", "pending_count")
        _summarise_bopis(result)
    return result


def get_replenishment_status(product_id: str = "", store_id: str = "", tool_context: ToolContext | None = None) -> dict:
    """Inbound replenishment lines for the store (scheduled | in_transit | received | delayed) with expected dates.

    Args:
        product_id: optional product id filter (e.g. P-0101).
        store_id: leave empty for the signed-in user's store.
    """
    sid, error = _scope(store_id, tool_context)
    if error:
        return error
    if bad := _bad_product_id(product_id):
        return bad
    return make_backend().get_replenishment_status(store_id=sid, product_id=product_id or None)


def get_task_status(product_id: str = "", status: str = "open", store_id: str = "", tool_context: ToolContext | None = None) -> dict:
    """Store tasks by status (default: the open ones), optionally for one product. Use it before creating a
    task so the same work is not raised twice. Each row carries `assignee_name`, and an open row says whether it is
    `overdue` (and by how many hours) at the store's clock: say so when you list it.

    Args:
        product_id: optional product filter: its id (P-0101) or its name as the manager said it.
        status: open | done | cancelled; empty = all.
        store_id: leave empty for the signed-in user's store.
    """
    sid, error = _scope(store_id, tool_context)
    if error:
        return error
    if product_id:   # the task agent has no catalog lookup of its own, so a name is resolved here, never guessed
        product, error = _resolve_product(product_id)
        if error:
            return error
        product_id = product["product_id"]
    if status and status not in F.TASK_STATUSES:
        return err(f"status must be one of {F.TASK_STATUSES} or empty")
    backend = make_backend()
    result = backend.get_task_status(store_id=sid, product_id=product_id or None, status=status or None)
    if result.get("status") == "SUCCESS":
        _annotate_tasks(result.get("rows", []), backend.list_associates(store_id=sid))
    return result


def _annotate_tasks(rows: list[Row], associates: dict) -> None:
    """What a manager needs to read a task list and a model should not have to work out: who an assignee id is, and
    whether an open task is already past due (a list that says "due 04:00" at 09:00 without a word hides the problem)."""
    names = {a["associate_id"]: a["first_name"] for a in associates.get("rows", [])} if associates.get("status") == "SUCCESS" else {}
    for row in rows:
        if row.get("assignee_id"):
            row["assignee_name"] = names.get(row["assignee_id"], "not at this store")
        if row.get("status") == "open" and row.get("due_at"):
            late = NOW - parse_ts(row["due_at"])
            row["overdue"] = late.total_seconds() > 0
            if row["overdue"]:
                row["overdue_by_hours"] = round(late.total_seconds() / 3600, 1)


# ---- associate orchestration (sheet row 2) --------------------------------------------------------------
def get_shift_roster(at_iso: str = "", window_hours: int = 4, focus: str = DEFAULT_COVERAGE_FOCUS,
                     store_id: str = "", tool_context: ToolContext | None = None) -> dict:
    """Who is on shift at a moment, with skills and current task, plus the coverage recommendation.

    `rows` is the roster at `at_iso`; `candidates` are the free associates (no current task) whose skills include
    `focus`, ordered by whether they cover the whole window and then by earliest shift end;
    `recommended_assignee_id` is the first candidate (empty when nobody qualifies).
    Skills are recorded working skills; this source does not record certifications or course completion.

    Args:
        at_iso: ISO timestamp; empty = the workshop clock (2026-10-03T09:00:00-05:00).
        window_hours: how long the coverage is needed for (1-12): "until 11" from the 09:00 clock is 2, "by close"
            is 12 (stores close 21:00). Only people on shift inside the window are listed.
        focus: the skill needed: bopis | skincare | fragrance | makeup | haircare | cash_wrap | backroom.
        store_id: leave empty for the signed-in user's store.
    """
    sid, error = _scope(store_id, tool_context)
    if error:
        return error
    if focus not in F.SKILLS:
        return err(f"focus must be one of {F.SKILLS}")
    at = parse_ts(at_iso) if at_iso else NOW
    hours = max(1, min(int(window_hours), 12))
    result = make_backend().get_shift_roster(store_id=sid, at_iso=at.isoformat())
    if result.get("status") != "SUCCESS":
        return result
    window_end = at + timedelta(hours=hours)
    cands = coverage_candidates(result["rows"], focus=focus, window_end=window_end)
    result.update({"candidates": cands, "recommended_assignee_id": cands[0]["associate_id"] if cands else "",
                   "focus": focus, "window_start": at.isoformat(), "window_end": window_end.isoformat(),
                   "skills_semantics": "Recorded working skills, not certification or course-completion records."})
    return result


def get_traffic_and_backlog(hours: int = 4, store_id: str = "", tool_context: ToolContext | None = None) -> dict:
    """Expected hourly traffic (visitors, transactions, sales) for the next `hours` plus `pending_bopis`, the
    number of pick-up orders promised within that window, with their `earliest_promise` and `latest_promise`.
    `window_end` is the end of the query window, not a deadline. Rising traffic with a backlog means a coverage gap.

    Args:
        hours: window length from the workshop clock (1-12).
        store_id: leave empty for the signed-in user's store.
    """
    sid, error = _scope(store_id, tool_context)
    if error:
        return error
    result = make_backend().get_traffic_and_backlog(store_id=sid, hours=max(1, min(int(hours), 12)))
    if result.get("status") == "SUCCESS" and _fault() == "stale_backlog":
        _stale_backlog(result, None, "pending_bopis")
    return result


# ---- loss prevention (sheet row 4) ----------------------------------------------------------------------
def get_shrink_signals(product_id: str = "", days: int = 14, store_id: str = "", tool_context: ToolContext | None = None) -> dict:
    """Shrink events (damage | unknown_loss | return_anomaly | adjustment) grouped by product and type over the
    last `days`, with per-product totals and a recommendation (investigate | monitor | inconclusive). Rows never name a person. Manager access only.

    Args:
        product_id: optional product id filter (e.g. P-0420).
        days: look-back window in days (1-90).
        store_id: leave empty for the signed-in user's store.
    """
    sid, error = _manager_scope(store_id, tool_context)
    if error:
        return error
    if bad := _bad_product_id(product_id):
        return bad
    result = make_backend().get_shrink_signals(store_id=sid, product_id=product_id or None, days=max(1, min(int(days), 90)))
    if result.get("status") != "SUCCESS":
        return result
    totals: dict[str, dict[str, Any]] = {}
    for row in result["rows"]:
        t = totals.setdefault(row["product_id"], {"product_id": row["product_id"], "product_name": row.get("product_name"),
                                                  "locked_case": row.get("locked_case"), "events": 0, "qty": 0, "value_usd": 0.0,
                                                  "units_by_type": {}})
        t["events"] += int(row["events"])
        t["qty"] += int(row["qty"])
        kind = row.get("event_type", "unspecified")
        t["units_by_type"][kind] = t["units_by_type"].get(kind, 0) + int(row["qty"])
        t["value_usd"] = round(t["value_usd"] + float(row["value_usd"]), 2)
    products = sorted(totals.values(), key=lambda t: (-t["value_usd"], t["product_id"]))
    for t in products:
        recommendation = shrink_recommendation(t["events"], t["value_usd"])
        t["recommendation"] = "inconclusive" if not result["complete"] and recommendation == "monitor" else recommendation
        t["total_recorded_units"] = t["qty"]
        t["unknown_loss_units"] = t["units_by_type"].get("unknown_loss", 0)
        t["quantity_description"] = "Total combines unknown loss, damage, adjustment and return anomaly; not all units are missing."
    complete = result["complete"]
    result["query_scope"] = {"store_id": sid, "product_id": product_id or None,
                             "window_start": result["window_start"], "window_end": result["window_end"]}
    result["complete"] = complete
    result["returned_group_count"] = len(result["rows"])
    result["recorded_totals"] = ({"events": sum(t["events"] for t in products),
                                  "units": sum(t["qty"] for t in products),
                                  "value_usd": round(sum(t["value_usd"] for t in products), 2)} if complete else None)
    result["result_semantics"] = ("Complete search of recorded events in query_scope; an empty result means zero recorded events in that scope."
                                  if complete else "Group limit reached; product and event totals may be partial.")
    result["products"] = products
    result["thresholds"] = {"events": SHRINK_INVESTIGATE_EVENTS, "value_usd": SHRINK_INVESTIGATE_VALUE_USD}
    result["rule"] = (f"investigate when a product has at least {SHRINK_INVESTIGATE_EVENTS} events or at least "
                      f"${SHRINK_INVESTIGATE_VALUE_USD:.0f} of value lost in the window (either one is enough); otherwise monitor only for complete results, or inconclusive for partial results")
    return result


def get_sales_pattern(product_id: str = "", days: int = 14, store_id: str = "", tool_context: ToolContext | None = None) -> dict:
    """Daily visitors, transactions and sales for the store over the last `days` (store-level; the workshop data
    has no per-product sales). Use it to see whether shrink coincides with a sales change.

    Args:
        product_id: echoed back for context; the pattern is store-level.
        days: look-back window in days (1-90).
        store_id: leave empty for the signed-in user's store.
    """
    sid, error = _scope(store_id, tool_context)
    if error:
        return error
    if bad := _bad_product_id(product_id):
        return bad
    return make_backend().get_sales_pattern(store_id=sid, product_id=product_id or None, days=max(1, min(int(days), 90)))


def get_task_history(product_id: str = "", days: int = 14, store_id: str = "", tool_context: ToolContext | None = None) -> dict:
    """Tasks of every status created in the last `days`, newest first (what has already been tried). A done task
    carries `completed_at: "not recorded"`: the data holds no completion date, so never state one. Manager access only.

    Args:
        product_id: optional product id filter.
        days: look-back window in days (1-90).
        store_id: leave empty for the signed-in user's store.
    """
    sid, error = _manager_scope(store_id, tool_context)
    if error:
        return error
    if bad := _bad_product_id(product_id):
        return bad
    result = make_backend().get_task_history(store_id=sid, product_id=product_id or None, days=max(1, min(int(days), 90)))
    for row in result.get("rows", []):
        if row.get("status") == "done":
            row["completed_at"] = "not recorded"
    return result


# ---- daily briefing and associate development (sheet rows 1 and 5) --------------------------------------
def get_guest_feedback(days: int = 7, store_id: str = "", tool_context: ToolContext | None = None) -> dict:
    """Guest feedback for the store over the last `days` (rating 1-5, topic, synthetic comment) plus a
    `summary` with the average rating and the low ratings (<= 2) per topic.

    Args:
        days: look-back window in days (1-90).
        store_id: leave empty for the signed-in user's store.
    """
    sid, error = _manager_scope(store_id, tool_context)
    if error:
        return error
    result = make_backend().get_guest_feedback(store_id=sid, days=max(1, min(int(days), 90)))
    if result.get("status") != "SUCCESS":
        return result
    rows = result["rows"]
    low: dict[str, int] = {}
    for r in rows:
        if int(r["rating"]) <= 2:
            low[r["topic"]] = low.get(r["topic"], 0) + 1
    result["summary"] = {"count": len(rows), "avg_rating": round(sum(int(r["rating"]) for r in rows) / len(rows), 2) if rows else None,
                         "low_ratings_by_topic": dict(sorted(low.items(), key=lambda kv: (-kv[1], kv[0])))}
    return result


ASSOCIATE_ID = re.compile(r"A-\d{3,6}")


def get_coaching_signals(associate_id: str, period: str = "", tool_context: ToolContext | None = None) -> dict:
    """Performance and coaching signals for one associate (bopis_pick_rate, cycle_count_accuracy, guest_rating,
    task_completion per ISO week). For store managers and district managers only; a store manager can only
    read associates of their own store. Never use it for HR or disciplinary decisions.

    Args:
        associate_id: an associate id (A-1007) or a first name at the signed-in store (Noor); never ask the
            manager for the id when they gave a name.
        period: ISO week like 2026-W39; empty = every period on file.
    """
    state = _state(tool_context)
    role = state.get(STATE_ROLE)
    if role == "associate":
        return err("coaching signals are available to store managers and district managers only")
    associate_id = associate_id.strip()
    if not ASSOCIATE_ID.fullmatch(associate_id):
        sid = state.get(STATE_STORE_ID)
        if not sid:
            return err(NO_STORE_IN_SCOPE)
        person, error = _resolve_associate(sid, associate_id)
        if error:
            return error
        associate_id = person["associate_id"]
    result = make_backend().get_coaching_signals(associate_id=associate_id, period=period or None)
    if result.get("status") != "SUCCESS":
        return result
    if role == "store_manager" and result["associate"]["store_id"] != state.get(STATE_STORE_ID):
        return err(f"{associate_id} works at {result['associate']['store_id']}, outside your store", code="forbidden")
    return result


# ---- the only writes: approve or delegate a task, each behind a confirmation that names what is written --
WRITES_PER_REQUEST = 2   # create + delegate is the most one request needs; more means the agent is looping


def _resolve_associate(sid: str, who: str) -> tuple[dict | None, dict | None]:
    """A person at this store from an id (A-1004) or a first name (Priya); never a guess.

    Managers talk in first names. Unknown or ambiguous names come back as errors that list who works here, so the
    agent asks the manager instead of trying ids."""
    listing = make_backend().list_associates(store_id=sid)
    if listing.get("status") != "SUCCESS":
        return None, listing
    people = listing["rows"]
    q = who.strip().lower()
    matches = [a for a in people if a["associate_id"].lower() == q] or [a for a in people if a["first_name"].lower() == q]
    roster = ", ".join(f"{a['first_name']} ({a['associate_id']})" for a in people if a["role"] != "district_manager")
    if not matches:
        return None, err(f"{who!r} is not an associate at {sid}. Ask the manager who they meant; people here: {roster}",
                         code="not_found")
    if len(matches) > 1:
        return None, err(f"{who!r} matches {len(matches)} people at {sid}: "
                         + ", ".join(f"{a['first_name']} ({a['associate_id']})" for a in matches) + ". Ask the manager which one.",
                         code="ambiguous")
    return matches[0], None


def _resolve_product(product: str) -> tuple[dict | None, dict | None]:
    """A catalog product from an id (P-0101) or the name the manager used (Lumière Hydra Cream); never a guess.

    Managers name products, not ids. One match is used, and the confirmation shows its name and id so the manager
    sees what was understood before anything is written. No match or several come back as errors that list the
    candidates, so the agent asks instead of picking."""
    backend = make_backend()
    wanted = product.strip()
    if PRODUCT_ID.fullmatch(wanted):
        found = backend.get_product_details(wanted)
        if found.get("status") != "SUCCESS" or not found.get("rows"):
            return None, err(f"product {wanted} is not in the catalog; check the id with the manager", code="not_found")
        return found["rows"][0], None
    listing = backend.search_products(query_text=wanted, category=None, max_price=None, fragrance_free=None,
                                      skin_type=None, limit=8)
    if listing.get("status") != "SUCCESS":
        return None, listing
    rows = listing.get("rows", [])
    exact = [r for r in rows if fold(r.get("name", "")) == fold(wanted)]
    matches = exact or rows
    if not matches:
        return None, err(f"no product matches {wanted!r}. Ask the manager for the product id or the exact name.",
                         code="not_found")
    if len(matches) > 1:
        return None, err(f"{wanted!r} matches {len(matches)} products: "
                         + ", ".join(f"{r['name']} ({r['product_id']})" for r in matches[:6]) + ". Ask the manager which one.",
                         code="ambiguous")
    return matches[0], None


def _resolve_assignee(sid: str, assignee: str) -> tuple[dict | None, dict | None]:
    """An associate who can take a task: resolved like any person here, minus the district manager."""
    matches, error = _resolve_associate(sid, assignee)
    if error:
        return None, error
    matches = [matches]
    if matches[0]["role"] == "district_manager":
        return None, err(f"{matches[0]['first_name']} ({matches[0]['associate_id']}) is the district manager; tasks go to store staff",
                         code="invalid_assignee")
    return matches[0], None


def _write_budget_exhausted(tool_context: ToolContext) -> dict | None:
    """Deterministic loop guard: at most WRITES_PER_REQUEST confirmed writes per user request (invocation)."""
    key = f"writes:{getattr(tool_context, 'invocation_id', 'local')}"
    if int(tool_context.state.get(key, 0)) >= WRITES_PER_REQUEST:
        return err(f"this request already made {WRITES_PER_REQUEST} changes; stop and ask the manager before any more",
                   code="write_budget")
    return None


def _count_write(tool_context: ToolContext) -> None:
    key = f"writes:{getattr(tool_context, 'invocation_id', 'local')}"
    tool_context.state[key] = int(tool_context.state.get(key, 0)) + 1


def _needs_confirmation(tool_context: ToolContext, hint: str, payload: dict) -> dict | None:
    """None when the write may go ahead; otherwise the envelope to return now.

    The first call asks the person to confirm (the runner pauses the invocation and the UI shows `hint`); the
    resumed call carries their answer in `tool_context.tool_confirmation`. A rejection writes nothing. Turn it off
    only with `store_tasks.require_confirmation: false` in config/envs/<env>.yaml.

    ADK docs:
      Human-in-the-loop: https://adk.dev/workflows/patterns/#human-in-the-loop
      Advanced tool confirmation: https://adk.dev/tools-custom/confirmation/#advanced-confirmation
    Workshop pages: docs/patterns/07-human-in-the-loop.md
    """
    if not load_env_config().store_tasks_require_confirmation:
        return None
    confirmation = getattr(tool_context, "tool_confirmation", None)
    if confirmation is None:
        tool_context.request_confirmation(hint=hint, payload=payload)
        return {"status": "PENDING_CONFIRMATION", "hint": hint}
    if not confirmation.confirmed:
        # A coordinator cannot restart a declined action in this invocation by rephrasing it.
        # A later explicit user request has a new invocation ID and is evaluated normally.
        tool_context.state["last_declined_action"] = {"invocation_id": tool_context.invocation_id}
        return err("the manager rejected this; nothing was written. Do not retry; ask what they want instead.", code="rejected")
    return None


def _task_key(tool_context: ToolContext, *parts: str) -> str:
    """Idempotency key for a write: derived from the write itself (operation, store, type, product, assignee, note),
    so a retried confirmation, a resumed invocation or the same request in a later message all find the original
    row instead of making a second one. Not kept in state: ADK drops `temp:` keys when an invocation ends, and a
    random key per invocation let a repeated approval create a duplicate task."""
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:32]


def create_store_task(task_type: Literal["backroom_check", "replenish", "cycle_count", "coverage_move",
                                       "investigation", "coaching", "planogram_fix", "signage_fix"],
                      note: str, product_id: str = "", assignee_id: str = "",
                      due_at: str = "", tool_context: ToolContext | None = None) -> dict:
    """Create a store task at the signed-in user's store (the approve step of the action plan). The task is due four
    hours after it is created unless an explicit deadline is supplied.

    Idempotent: repeating the same call in a session returns the original task with `already_created: true`.

    Args:
        task_type: backroom_check | replenish | cycle_count | coverage_move | investigation | coaching | planogram_fix | signage_fix.
        note: one sentence saying what to do and why (the signals behind it).
        product_id: optional product the task is about: its id (P-0101) or its name as the manager said it
            (Lumière Hydra Cream). Never guess an id.
        assignee_id: optional associate to assign it to: their id (A-1004) or first name (Priya) as the manager
            said it; leave empty to create it unassigned. Never guess an id.
        due_at: optional ISO deadline including timezone offset, e.g. 2026-10-03T09:30:00-05:00.
    """
    if tool_context is None:
        return err("create_store_task needs the session context")
    if due_at:
        try:
            due = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
        except ValueError:
            return err("due_at must be an ISO timestamp with the store timezone offset.")
        if due.tzinfo is None or due < NOW:
            return err("The deadline must include its timezone and must not be in the past.")
    else:
        due = NOW + timedelta(hours=4)
    due_at = due.isoformat()
    sid, error = _scope("", tool_context)
    if error:
        return error
    if task_type not in F.TASK_TYPES:
        return err(f"task_type must be one of {F.TASK_TYPES}")
    budget = _write_budget_exhausted(tool_context)
    if budget:
        return budget
    who = ""
    if assignee_id:
        person, error = _resolve_assignee(sid, assignee_id)
        if error:
            return error
        assignee_id, who = person["associate_id"], f"{person['first_name']} ({person['associate_id']})"
    if product_id:
        product, error = _resolve_product(product_id)
        if error:
            return error
        product_id = product["product_id"]
        what = f" for {product.get('name', product_id)} ({product_id})"
    else:
        what = ""
    hint = f"Create a {task_type} task at {sid}{what}, " + (f"assigned to {who}" if who else "unassigned") + f': "{note}"'
    hint += f" · Due {due.astimezone(NOW.tzinfo).strftime('%b %d, %I:%M %p')}"
    pending = _needs_confirmation(tool_context, hint, {"task_type": task_type, "product_id": product_id,
                                                       "assignee_id": assignee_id, "note": note, "due_at": due_at})
    if pending:
        return pending
    _count_write(tool_context)
    key = _task_key(tool_context, "create", sid, task_type, product_id, assignee_id, note, due_at)
    return make_backend().create_store_task(store_id=sid, task_type=task_type, product_id=product_id or None,
                                            assignee_id=assignee_id or None, note=note, task_key=key, due_at=due_at)


def delegate_task(task_id: str, assignee_id: str, tool_context: ToolContext | None = None) -> dict:
    """Assign an open task at the signed-in user's store to an associate of that store (the delegate step).

    Only open tasks can be delegated; a done or cancelled task returns a conflict. Repeating the same call in a
    session returns the task unchanged.

    Args:
        task_id: e.g. T-00137.
        assignee_id: the associate's id (A-1004) or first name (Priya) as the manager said it. Never guess an id.
    """
    if tool_context is None:
        return err("delegate_task needs the session context")
    sid, error = _scope("", tool_context)
    if error:
        return error
    budget = _write_budget_exhausted(tool_context)
    if budget:
        return budget
    person, error = _resolve_assignee(sid, assignee_id)
    if error:
        return error
    assignee_id = person["associate_id"]
    pending = _needs_confirmation(tool_context, f"Delegate task {task_id} at {sid} to {person['first_name']} ({assignee_id})",
                                  {"task_id": task_id, "assignee_id": assignee_id})
    if pending:
        return pending
    _count_write(tool_context)
    key = _task_key(tool_context, "delegate", sid, task_id, assignee_id)
    return make_backend().delegate_task(store_id=sid, task_id=task_id, assignee_id=assignee_id, task_key=key)
