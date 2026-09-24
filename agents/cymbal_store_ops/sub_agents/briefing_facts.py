"""Decision inputs for the briefing writer, without duplicated connector payloads.

Full tool results remain in ADK events. This projection keeps source failures and
uncertainties, uses complete aggregates only when the source marks them complete,
and never limits the number of records. It does not make priority decisions.
"""
from __future__ import annotations

import json
from copy import deepcopy

from agents.cymbal_store_ops.tools.data_backend import parse_ts

# Descriptive store columns repeat session scope; idempotency keys are write internals.
_ROW_NOISE = {"store_name", "city", "state", "task_key", "delegation_key"}
_TASK_NOISE = _ROW_NOISE
_STOCK_NOISE = _ROW_NOISE


def _without(row, keys):
    return {key: deepcopy(value) for key, value in row.items() if key not in keys}


def _tasks(rows):
    return [_without(row, _TASK_NOISE) for row in rows]


def _demand(result):
    value = deepcopy(result)
    if value.get("status") != "SUCCESS":
        return value
    # Summaries preserve separate order/unit counts and both promise endpoints.
    # A partial or unknown summary cannot substitute for its underlying rows.
    products = value.get("by_product")
    if (value.get("by_product_complete") is True and isinstance(products, list)
            and all(row.get("promise_times_complete") is True for row in products)
            and sum(row.get("orders", 0) for row in products) == value.get("pending_count")
            and sum(row.get("units", 0) for row in products) == value.get("units_total")
            and _demand_rows_match(value)):
        value.pop("rows", None)
    return value


def _demand_rows_match(value):
    """Keep raw rows if the aggregate contradicts them or carries unknown evidence."""
    rows = value.get("rows", [])
    known = {"order_id", "store_id", "product_id", "qty", "promised_at", "status",
             "product_name", "category", "locked_case", "price_usd"}
    if any(set(row) - known or row.get("status") != "pending" for row in rows):
        return False
    try:
        for product in value["by_product"]:
            matching = [row for row in rows if row["product_id"] == product["product_id"]]
            if len(matching) != product["orders"] or sum(row["qty"] for row in matching) != product["units"]:
                return False
            if matching and (min(parse_ts(row["promised_at"]) for row in matching) != parse_ts(product["earliest_promise"])
                             or max(parse_ts(row["promised_at"]) for row in matching) != parse_ts(product["latest_promise"])):
                return False
        return len(rows) == value["pending_count"]
    except (KeyError, TypeError, ValueError):
        return False


def _inventory_context(result):
    value = deepcopy(result)
    for row in value.get("rows", []):
        if "stock" in row:
            row["stock"] = _without(row["stock"], _STOCK_NOISE)
        if "demand" in row:
            row["demand"] = _demand(row["demand"])
        if "open_tasks" in row:
            row["open_tasks"] = _tasks(row["open_tasks"])
        if "inbound" in row:
            row["inbound"] = [_without(record, _ROW_NOISE | {"category", "locked_case", "price_usd"})
                              for record in row["inbound"]]
        # Keep allocation observations/movements/reservations, failed picks and computed
        # uncertainty together. The resulting ATP alone cannot explain a discrepancy.
    return value


def _roster(result):
    value = deepcopy(result)
    roster = {}
    for row in value.get("rows", []):
        if "assigned_tasks" in row:
            row["assigned_tasks"] = _tasks(row["assigned_tasks"])
        if row.get("associate_id"):
            roster[row["associate_id"]] = row
    for candidate in value.get("candidates", []):
        existing = roster.get(candidate.get("associate_id"))
        if not existing:
            continue  # An unmatched candidate must retain its complete source record.
        if "assigned_tasks" in candidate:
            candidate["assigned_tasks"] = _tasks(candidate["assigned_tasks"])
        for key in list(candidate):
            if key != "associate_id" and key in existing and candidate[key] == existing[key]:
                del candidate[key]
    return value


def _feedback(result):
    value = deepcopy(result)
    # Keep every distinct observation, including positive feedback. Repeated records
    # do not need identical text/name columns repeated for the planning decision.
    grouped = {}
    for row in value.get("rows", []):
        observation = _without(row, {"feedback_id", "store_id", "submitted_at"})
        key = json.dumps(observation, sort_keys=True, default=str)
        if key not in grouped:
            grouped[key] = {**observation, "count": 0, "first_submitted_at": None,
                            "last_submitted_at": None}
        item = grouped[key]
        item["count"] += 1
        submitted = row.get("submitted_at")
        if submitted:
            item["first_submitted_at"] = min(filter(None, [item["first_submitted_at"], submitted]), key=parse_ts)
            item["last_submitted_at"] = max(filter(None, [item["last_submitted_at"], submitted]), key=parse_ts)
    if "rows" in value:
        value["observations"] = list(grouped.values())
        del value["rows"]
    return value


def _loss(result):
    value = deepcopy(result)
    # Product totals and event-type components answer different questions. Keep both;
    # remove only product descriptions duplicated identically in the product summary.
    products = {row.get("product_id"): row for row in value.get("products", [])}
    for row in value.get("rows", []):
        product = products.get(row.get("product_id"), {})
        for key in ("product_name", "locked_case"):
            if key in product and row.get(key) == product[key]:
                row.pop(key, None)
        row.pop("category", None)
        row.pop("price_usd", None)  # Component value_usd and quantities are retained.
    return value


def project_tool_result(name: str, result):
    """Project one briefing source, with unknown/failed tools unchanged.

    This is briefing-specific: full per-order pickup feasibility is supplied by the
    coverage branch. Do not apply these aggregate projections to arbitrary specialist
    questions that may require an individual order or feedback record's identity.
    """
    if not isinstance(result, dict) or result.get("status") != "SUCCESS":
        return deepcopy(result)
    if name == "get_bopis_demand":
        return _demand(result)
    if name == "get_inventory_context":
        return _inventory_context(result)
    if name in {"get_task_status", "get_task_history"}:
        return {**deepcopy(result), "rows": _tasks(result.get("rows", []))}
    if name == "get_osa_exceptions":
        return {**deepcopy(result), "rows": [_without(row, _STOCK_NOISE) for row in result.get("rows", [])]}
    if name == "get_shift_roster":
        return _roster(result)
    if name == "get_guest_feedback":
        return _feedback(result)
    if name == "get_shrink_signals":
        return _loss(result)
    # Coverage rules, per-order feasibility, directives and controls carry
    # their source/timestamp and full context, including unknown new fields.
    return deepcopy(result)


def project_briefing_facts(area: str, results: dict) -> dict:
    """Keep exact facts per source; return an independent object without modifying trace data."""
    if area not in {"inventory", "coverage", "shrink"}:
        raise ValueError(f"Unknown briefing area: {area}")
    return {name: project_tool_result(name, result) for name, result in results.items()}


def pack_writer_tables(value):
    """Encode homogeneous record lists once by column, preserving every value.

    Used only in the writer's request, never in tool results or stored evidence.
    Different key sets remain ordinary objects so absent fields stay distinct
    from explicit nulls. This changes representation, not selection or priority.
    """
    if isinstance(value, dict):
        return {key: pack_writer_tables(item) for key, item in value.items()}
    if not isinstance(value, list):
        return value
    if len(value) >= 3 and all(isinstance(row, dict) for row in value):
        columns = list(value[0])
        if columns and all(set(row) == set(columns) for row in value):
            # Compare JSON, not Python equality: false and zero are different facts.
            common = {key: pack_writer_tables(value[0][key]) for key in columns
                      if len({json.dumps(row[key], sort_keys=True, ensure_ascii=False) for row in value}) == 1}
            varying = [key for key in columns if key not in common]
            packed = {"columns": varying,
                      "records": [[pack_writer_tables(row[key]) for key in varying] for row in value]}
            if common:
                packed["common"] = common
            if len(json.dumps(packed)) < len(json.dumps(value)):
                return packed
    return [pack_writer_tables(item) for item in value]


def _canonical_loss_measures(source):
    """Factor proven aliases once; disagreements and partial sources stay explicit.

    The declared aliases reconstruct every original product field. No product or
    event component is selected, ranked or removed. Unknown fields stay in place.
    """
    products = source["products"]
    if not products or source.get("complete") is not True or "product_measure_encoding" in source:
        return
    descriptions = [product.get("quantity_description") for product in products]
    aliases_match = True
    for product in products:
        components = product["recorded_event_type_breakdown"]
        by_type = {}
        for component in components:
            units = component.get("units")
            if type(units) is not int or not isinstance(component.get("event_type"), str):
                aliases_match = False
                break
            kind = component["event_type"]
            by_type[kind] = by_type.get(kind, 0) + units
        # JSON equality preserves the distinction between false, zero and 0.0.
        expected = {"qty": sum(by_type.values()), "total_recorded_units": sum(by_type.values()),
                    "units_by_type": by_type, "unknown_loss_units": by_type.get("unknown_loss", 0)}
        if ("units" in product or not components or
                any(key not in product or json.dumps(product[key], sort_keys=True) != json.dumps(value, sort_keys=True)
                    for key, value in expected.items())):
            aliases_match = False
    if not aliases_match:
        return
    encoding = {"units": "Original qty and total_recorded_units; a unit count, not an event count.",
                "units_by_type": "Exact sum of component units by event_type.",
                "unknown_loss_units": "Exact sum of unknown_loss component units; zero when that type is absent.",
                "applies_to": "Every product; all source component fields and records remain attached."}
    if isinstance(descriptions[0], str) and all(value == descriptions[0] for value in descriptions):
        encoding["shared_quantity_description"] = descriptions[0]
    for product in products:
        product["units"] = product.pop("qty")
        for key in ("total_recorded_units", "units_by_type", "unknown_loss_units"):
            del product[key]
        if "shared_quantity_description" in encoding:
            del product["quantity_description"]
    source["product_measure_encoding"] = encoding


def writer_facts(area: str, facts: dict) -> dict:
    """Join loss components to their product for reading, retaining every source row.

    This is a writer-input representation only. Full tool results and projected
    state stay unchanged. The component `units` field is the original `qty`;
    event counts, values, timestamps and unknown future fields remain independent.
    Unmatched rows remain explicit, so a limited product summary cannot lose them.
    """
    packed = pack_writer_tables(facts)
    if area == "coverage" and "get_pickup_workload" in facts:
        # Keep paired start/finish scenarios and each order's constraints together
        # as named objects. Positional tables obscure which times belong together.
        packed["get_pickup_workload"] = deepcopy(facts["get_pickup_workload"])
    source = facts.get("get_shrink_signals") if area == "shrink" else None
    if not isinstance(source, dict) or source.get("status") != "SUCCESS":
        return packed
    if not isinstance(source.get("rows"), list) or not isinstance(source.get("products"), list):
        return packed
    if (any(key in source for key in ("ungrouped_rows", "breakdown_semantics")) or
            any("recorded_event_type_breakdown" in product for product in source["products"])):
        return packed  # A future source field must not be overwritten by representation metadata.
    joined = deepcopy(source)
    rows = joined.pop("rows")
    matched = set()
    for product in joined["products"]:
        components = []
        for index, row in enumerate(rows):
            if row.get("product_id") != product.get("product_id"):
                continue
            component = deepcopy(row)
            component.pop("product_id", None)
            if "qty" in component:
                if "units" in component:
                    raise ValueError("Loss component already contains both qty and units")
                component["units"] = component.pop("qty")
            components.append(component)
            matched.add(index)
        product["recorded_event_type_breakdown"] = components
    joined["ungrouped_rows"] = [row for index, row in enumerate(rows) if index not in matched]
    joined["breakdown_semantics"] = (
        "recorded_event_type_breakdown retains each source row for its parent product_id. "
        "events counts events; units is the source qty (unit count). All fields and rows remain, "
        "including ungrouped_rows. Investigation thresholds support recommendations, not mandatory policy.")
    _canonical_loss_measures(joined)
    # Keep this joined structure explicit: positional packing separates units from
    # event labels and asks the writer to perform the same joins again.
    packed["get_shrink_signals"] = joined
    return packed
