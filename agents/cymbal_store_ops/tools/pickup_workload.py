"""Explicit pickup workload arithmetic, separate from staffing judgment."""
from __future__ import annotations

import asyncio
from datetime import timedelta

from google.adk.tools import ToolContext

from agents.cymbal_store_ops.tools import domain_tools as domain
from agents.cymbal_store_ops.tools.data_backend import NOW, err, ok, parse_ts
from agents.cymbal_store_ops.tools.operations_tools import get_coverage_requirements


def _clock(moment) -> str:
    return moment.strftime("%I:%M %p").lstrip("0")


def promise_check(schedule: list[dict], start) -> str:
    """One sentence, computed here, on whether each order meets its own promise, so a queue finish time is never
    read against the first promise."""
    if not schedule:
        return "No pending pickup orders."
    local = start.tzinfo
    first = schedule[0]
    ready, due = parse_ts(first["estimated_finish"]).astimezone(local), parse_ts(first["promised_by"]).astimezone(local)
    late = [row for row in schedule if not row["within_promise"]]
    if not late:
        return (f"All {len(schedule)} orders finish by their own promise times; the first, due {_clock(due)}, "
                f"is ready about {_clock(ready)}.")
    miss = late[0]
    return (f"{len(late)} of {len(schedule)} orders would miss their promise; the first miss is {miss['order_id']}, "
            f"due {_clock(parse_ts(miss['promised_by']).astimezone(local))} and ready about "
            f"{_clock(parse_ts(miss['estimated_finish']).astimezone(local))}.")


def estimate_queue(orders: list[dict], minutes_per_order: float, start=NOW) -> dict:
    ordered = sorted(orders, key=lambda order: (parse_ts(order["promised_at"]), order["order_id"]))
    first_due = parse_ts(ordered[0]["promised_at"]) if ordered else None
    cursor = start
    schedule = []
    for order in ordered:
        cursor += timedelta(minutes=minutes_per_order)
        due = parse_ts(order["promised_at"])
        schedule.append({"order_id": order["order_id"], "product_id": order["product_id"], "units": order["qty"],
                         "promised_by": due.isoformat(), "estimated_finish": cursor.isoformat(),
                         "within_promise": cursor <= due})
    due_first = [row for row in schedule if parse_ts(row["promised_by"]) == first_due]
    # Every prefix of the earliest-deadline schedule must meet its own promise.
    # The tightest prefix, not necessarily the first or last order, sets the limit.
    latest_start = min((parse_ts(order["promised_at"]) - timedelta(minutes=(i + 1) * minutes_per_order)
                        for i, order in enumerate(ordered)), default=None)

    def scenario(scenario_start):
        # Pair each finish with the start that produced it. Display in the
        # snapshot's local offset; never alter source promise instants.
        local_start = scenario_start.astimezone(start.tzinfo)
        late = sum(local_start + timedelta(minutes=index * minutes_per_order) > parse_ts(order["promised_at"])
                   for index, order in enumerate(ordered, start=1))
        return {"start": local_start.isoformat(),
                "estimated_queue_finish": (local_start + timedelta(minutes=len(ordered) * minutes_per_order)).isoformat(),
                "orders_late_in_estimate": late,
                "start_at_or_after_snapshot": scenario_start >= start,
                "feasible_from_snapshot": scenario_start >= start and late == 0}

    return {"orders": schedule, "pending_order_count": len(ordered),
            "pending_unit_count": sum(order["qty"] for order in ordered),
            "estimated_minutes": len(ordered) * minutes_per_order, "start": start.isoformat(),
            "estimated_queue_finish": cursor.isoformat(),
            "latest_uninterrupted_start": latest_start.isoformat() if latest_start else None,
            "minimum_schedule_slack_minutes": (latest_start - start).total_seconds() / 60 if latest_start else None,
            "first_promise": first_due.isoformat() if first_due else None,
            "orders_due_at_first_promise": len(due_first),
            "units_due_at_first_promise": sum(row["units"] for row in due_first),
            "whole_queue_can_finish_by_first_promise": cursor <= first_due if first_due else True,
            "orders_late_in_estimate": sum(not row["within_promise"] for row in schedule),
            "promise_check": promise_check(schedule, start),
            "schedule_scenarios": {"snapshot_start": scenario(start),
                                   "latest_uninterrupted_start": scenario(latest_start) if latest_start else None},
            "basis": "One available picker, continuous work, earliest promises first; excludes breaks, interruptions and stock exceptions. "
                     "start is the simulation assumption, not a required start or staging deadline. "
                     "latest_uninterrupted_start is an estimate under these assumptions, not a guaranteed safe start. "
                     "Each schedule_scenarios entry pairs its start with its own finish and late count; do not mix alternatives. "
                     "The detailed orders schedule uses the snapshot start. Both alternatives use every order's promise. "
                     "A scenario starting before the snapshot cannot be achieved from now. Scenario timestamps use the snapshot's local offset.",
            "minutes_per_order": minutes_per_order}


async def get_pickup_workload(hours: int = 2, tool_context: ToolContext | None = None) -> dict:
    """Pickup deadlines and computed work estimate for one uninterrupted picker starting now.

    Returns complete queue order/unit totals and per-order deadlines.
    Distinguishes orders due at the first promise from the entire queue. Combine with the roster,
    breaks and stock constraints before proposing an assignment; this is an estimate, not a service promise.
    """
    demand, requirements = await asyncio.gather(
        asyncio.to_thread(domain.get_bopis_demand, hours=hours, tool_context=tool_context),
        asyncio.to_thread(get_coverage_requirements, tool_context=tool_context))
    for result in (demand, requirements):
        if result.get("status") != "SUCCESS":
            return result
    rows = requirements.get("rows", [])
    if len(rows) != 1 or not demand.get("by_product_complete") or not all(item.get("promise_times_complete") for item in demand.get("by_product", [])):
        return err("Complete pickup promises and one workforce planning record are needed for a work estimate.")
    minutes = rows[0]["payload"].get("planning_estimates", {}).get("bopis_order_minutes")
    if not isinstance(minutes, (int, float)) or minutes <= 0:
        return err("A positive order-picking estimate is needed.")
    return ok([estimate_queue(demand["rows"], minutes)])
