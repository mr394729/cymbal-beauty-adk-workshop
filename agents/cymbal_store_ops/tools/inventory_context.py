"""Concurrent inventory evidence reads and deterministic allocation arithmetic."""
from __future__ import annotations

import asyncio

from google.adk.tools import ToolContext

from agents.cymbal_store_ops.tools import domain_tools as domain
from agents.cymbal_store_ops.tools.data_backend import NOW, err, ok, parse_ts


def _allocation_decision(stock: dict, allocation: dict, location: dict, demand: dict) -> dict:
    """Separate reservations from demand and only recommend a check for a specific evidence gap."""
    issues = []
    if not allocation:
        return {"action": "resolve_inventory_evidence", "evidence_gaps": ["allocation_evidence_missing"],
                "reservations_known": False, "reserved_units": None, "observed_reserved_units": None,
                "pending_order_count": demand.get("pending_count"),
                "pending_demand_units": demand.get("units_total"), "unreserved_pending_units": None,
                "available_to_promise_units": None, "shelf_replenishment_units": None,
                "quantity_basis": None, "stock_observation_age_minutes": None,
                "physical_check_needed": False}
    if allocation.get("quantity_basis") != "gross_saleable_including_reservations":
        issues.append("quantity_basis_unknown")
    reservations_known = allocation.get("reservations_complete") is True and isinstance(allocation.get("reservations"), list)
    if not reservations_known:
        issues.append("reservation_coverage_incomplete")
    observed = allocation.get("observed_at")
    age = (NOW - parse_ts(observed)).total_seconds() / 60 if observed else None
    if age is None or age < 0 or age > allocation.get("freshness_minutes", 0):
        issues.append("stock_observation_stale_or_missing")
    for key in ("on_hand", "on_shelf_qty", "backroom_qty"):
        if allocation.get(f"observed_{key}") != stock[key]:
            issues.append("stock_count_conflict")
            break
    if allocation.get("last_failed_pick"):
        issues.append("failed_pick_requires_reconciliation")
    if not location.get("backstock_location"):
        issues.append("stock_location_missing")
    reservations = [r for r in allocation.get("reservations") or [] if r.get("status") == "active"]
    reserved = sum(int(r["qty"]) for r in reservations)
    if any(int(r["qty"]) <= 0 for r in reservations) or reserved > stock["on_hand"]:
        issues.append("reservation_quantity_conflict")
    order_rows = demand.get("rows", [])
    orders = {r["order_id"]: r for r in order_rows}
    if len(orders) != len(order_rows):
        issues.append("duplicate_demand_records")
    by_order = {}
    for reservation in reservations:
        oid = reservation["order_id"]
        by_order[oid] = by_order.get(oid, 0) + int(reservation["qty"])
    if any(by_order.get(oid, 0) > int(order["qty"]) for oid, order in orders.items()):
        issues.append("reservation_order_conflict")
    demand_complete = demand.get("by_product_complete", False)
    if not demand_complete:
        issues.append("demand_coverage_incomplete")
    unreserved = sum(max(0, int(order["qty"]) - by_order.get(oid, 0)) for oid, order in orders.items())
    # ATP excludes explicit reservations ONCE. Unreserved pending demand is a separate commitment risk.
    atp = max(0, int(stock["on_hand"]) - reserved) if not issues else None
    free_after_demand = max(0, atp - unreserved) if atp is not None else None
    shelf_units = min(int(stock["backroom_qty"]), max(0, int(stock["shelf_capacity"]) - int(stock["on_shelf_qty"])),
                      free_after_demand) if free_after_demand is not None else None
    physical_reasons = {"stock_count_conflict", "failed_pick_requires_reconciliation", "stock_location_missing",
                        "stock_observation_stale_or_missing"}
    action = ("resolve_stock_discrepancy" if physical_reasons.intersection(issues) else "resolve_inventory_evidence") if issues else (
        "allocate_pending_demand" if unreserved else "pick_reserved_then_replenish" if reserved else "replenish_shelf")
    return {"action": action, "evidence_gaps": issues, "stock_observation_age_minutes": age,
            "reservations_known": reservations_known, "reserved_units": reserved if reservations_known else None,
            "observed_reserved_units": reserved if isinstance(allocation.get("reservations"), list) else None,
            "pending_order_count": demand.get("pending_count"),
            "pending_demand_units": demand.get("units_total"),
            "unreserved_pending_units": unreserved if reservations_known else None,
            "available_to_promise_units": atp, "shelf_replenishment_units": shelf_units,
            "physical_check_needed": bool(physical_reasons.intersection(issues)),
            "quantity_basis": allocation.get("quantity_basis")}


def _open_tasks(product_id: str, tool_context: ToolContext) -> dict:
    if domain._state(tool_context).get("user:role") != "associate":
        return domain.get_task_status(product_id=product_id, tool_context=tool_context)
    from agents.cymbal_store_ops.tools.store_query import query_store_data
    # The generic query injects the signed-in associate predicate before paging.
    return query_store_data("tasks", fields=["task_id", "task_type", "product_id", "product_name",
        "assignee_id", "assignee_name", "status", "source", "created_at", "due_at", "note"],
        filters=[{"field": "product_id", "value": product_id}, {"field": "status", "value": "open"}],
        limit=100, tool_context=tool_context)


async def get_inventory_context(product_name: str, tool_context: ToolContext | None = None) -> dict:
    """Assess product availability flags with stock, reservations, pickup deadlines, locations and existing work.

    availability_flags reports the conditions raised by the recorded stock position.
    decision.evidence_gaps lists uncertainty in the allocation evidence, separately from those flags.

    Store scope comes from the signed-in session. Reads run concurrently after resolving one exact SKU.
    Available-to-promise subtracts active reservations once; pending demand remains a separate measure.
    Missing/incomplete allocation evidence means reserved units and availability are unknown, not zero;
    stock balances and known pickup demand remain available independently of that evidence gap.
    A targeted stock check is needed only for stale/missing observations, conflicts or a failed pick.
    Shelf capacity is a maximum, not a merchandising completion target.
    Task scope is the store for managers and only own assignments for associates.
    This tool reads evidence; it does not reserve, move stock, complete a pick or create work.

    Args:
        product_name: the product id (for example "P-0101") whenever you have one; several products share a
            display name, and a name that matches more than one product returns an error instead of a guess.
    """
    state = domain._state(tool_context)
    if not state.get("user:user_id") or state.get("user:role") not in {"associate", "store_manager", "district_manager"}:
        return err("Sign in before reading inventory context.", code="forbidden")
    sid, error = domain._scope("", tool_context)
    if error:
        return error
    if not product_name.strip():
        return err("Name the product to review.", code="invalid_argument")
    backend = domain.make_backend()
    stock_result = await asyncio.to_thread(backend.check_store_stock, product_name=product_name, store_id=sid)
    if stock_result.get("status") != "SUCCESS":
        return stock_result
    rows = stock_result.get("rows", [])
    if len(rows) != 1:
        return err("Choose one exact product.", code="ambiguous" if rows else "not_found",
                   matches=[{"product_id": r["product_id"], "product_name": r.get("product_name")} for r in rows])
    if domain._fault() == "stale_stock":
        domain._stale_stock(stock_result)
    stock = rows[0]
    pid = stock["product_id"]
    names = ("demand", "location", "allocation", "supply", "tasks")
    results = await asyncio.gather(
        asyncio.to_thread(domain.get_bopis_demand, product_id=pid, hours=24, tool_context=tool_context),
        asyncio.to_thread(backend.get_operations_context, store_id=sid, system="stock_location", subject_id=pid),
        asyncio.to_thread(backend.get_operations_context, store_id=sid, system="inventory_allocation", subject_id=pid),
        asyncio.to_thread(backend.get_replenishment_status, store_id=sid, product_id=pid),
        asyncio.to_thread(_open_tasks, product_id=pid, tool_context=tool_context),
    )
    sources = dict(zip(names, results, strict=True))
    for name, result in sources.items():
        if result.get("status") != "SUCCESS":
            return err(f"Inventory context could not read {name}: {result.get('error_details', 'read failed')}",
                       code="source_unavailable", failed_source=name)
    for name in ("location", "allocation"):
        if len(sources[name]["rows"]) > 1:
            return err(f"Multiple current {name} snapshots require reconciliation.", code="conflict")
    location = sources["location"]["rows"][0]["payload"] if sources["location"]["rows"] else {}
    allocation = sources["allocation"]["rows"][0]["payload"] if sources["allocation"]["rows"] else {}
    decision = _allocation_decision(stock, allocation, location, sources["demand"])
    decision["existing_open_task_count"] = sources["tasks"].get("total_matching", len(sources["tasks"]["rows"]))
    decision["inbound_delayed"] = any(r["status"] == "delayed" for r in sources["supply"]["rows"])
    source_availability = {name: "missing" if name in {"allocation", "location"} and not payload else "available"
                           for name, payload in (("stock", stock), ("location", location), ("allocation", allocation),
                                                 ("demand", sources["demand"]), ("supply", sources["supply"]),
                                                 ("tasks", sources["tasks"]))}
    allocation_evidence = ({**allocation, "source_status": "available"} if allocation else
                           {"source_status": "missing", "reservations": None, "reservations_complete": False,
                            "quantity_basis": None})
    availability_flags = []
    if stock["on_shelf_qty"] == 0 and stock["on_hand"] > 0:
        availability_flags.append("empty_shelf_with_store_stock")
    if stock["on_hand"] < stock["reorder_point"]:
        availability_flags.append("below_reorder_point")
    return ok([{"availability_flags": availability_flags, "stock": stock, "location": location, "allocation": allocation_evidence,
                "source_availability": source_availability,
                "demand": sources["demand"], "inbound": sources["supply"]["rows"],
                "open_tasks": sources["tasks"]["rows"],
                "task_scope": "own_assigned_tasks" if state["user:role"] == "associate" else "store",
                "task_page": {"returned_count": len(sources["tasks"]["rows"]),
                              "total_matching": sources["tasks"].get("total_matching"),
                              "has_more": sources["tasks"].get("has_more")},
                "field_semantics": {"shelf_capacity": "Physical shelf maximum; not a directive completion target."},
                "decision": decision}], store_id=sid,
              as_of=NOW.isoformat())
