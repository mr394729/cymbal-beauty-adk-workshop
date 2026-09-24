"""Composable, store-scoped reads: the model chooses fields, filters and aggregates.

SQL identifiers come exclusively from these published resource schemas. Values are
parameters, store scope is injected in code, and task records are self-scoped for
associates. No free-form SQL, personal coaching tables or write operations are exposed.
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from google.adk.tools import ToolContext
from google.api_core.exceptions import GoogleAPICallError
from pydantic import BaseModel, ConfigDict

from agents.cymbal_store_ops import fixtures
from agents.cymbal_store_ops.tools import data_backend
from agents.cymbal_store_ops.tools.data_backend import NOW, err, ok, parse_ts

ResourceName = Literal["inventory", "orders", "tasks", "traffic", "loss", "feedback", "reviews", "deliveries", "roster"]
DiscoveryResource = Literal["", "inventory", "orders", "tasks", "traffic", "loss", "feedback", "reviews", "deliveries", "roster"]


class RecordFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "contains", "is_null"] = "eq"
    value: str = ""


class Measure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["count", "sum", "avg", "min", "max"]
    field: str = ""  # Empty field is valid for count only.


class RecordOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    direction: Literal["asc", "desc"] = "asc"


@dataclass(frozen=True)
class Resource:
    table: str
    fake_attribute: str
    fields: dict[str, str]
    default_fields: tuple[str, ...]
    note: str
    product_join: bool = False
    manager_only: bool = False


PRODUCT = {"product_id": "text", "product_name": "text", "brand": "text", "category": "text",
           "subcategory": "text", "price_usd": "number", "locked_case": "boolean",
           "is_fragrance_free": "boolean", "skin_types": "text", "key_ingredients": "text",
           "rating_avg": "number", "rating_count": "integer"}
RESOURCES = {
    "inventory": Resource("store_inventory", "inventory", {
        **PRODUCT, "on_hand": "integer", "on_shelf_qty": "integer", "backroom_qty": "integer",
        "reorder_point": "integer", "shelf_capacity": "integer", "bopis_eligible": "boolean",
        "updated_at": "timestamp", "retail_value_usd": "number", "below_reorder": "boolean"},
        ("product_id", "product_name", "category", "on_hand", "on_shelf_qty", "backroom_qty"),
        "Recorded gross stock, not available-to-promise. Retail value uses selling price, not cost. All products, including healthy stock.", True),
    "orders": Resource("bopis_orders", "orders", {**PRODUCT, "order_id": "text", "qty": "integer",
        "promised_at": "timestamp", "status": "text"},
        ("order_id", "product_name", "qty", "promised_at", "status"),
        "Pickup orders: pending, picked, ready or collected. A promise is a ready-by deadline; quantities are units.", True),
    "tasks": Resource("store_tasks", "tasks", {"task_id": "text", "task_type": "text", "product_id": "text",
        "assignee_id": "text", "assignee_name": "text", "product_name": "text",
        "status": "text", "source": "text", "created_at": "timestamp", "due_at": "timestamp", "note": "text"},
        ("task_id", "task_type", "assignee_id", "assignee_name", "product_id", "product_name", "status", "due_at", "note"),
        "Open, done and cancelled work. Associates see only their own assignments; managers see store work. Read-only. "
        "Names are current display labels, not historical ownership. A null name means unavailable or ambiguous; "
        "a present ID still identifies the assigned person or product. Only a null assignee_id means unassigned."),
    "traffic": Resource("store_traffic", "traffic", {"ts_hour": "timestamp", "day": "date", "visitors": "integer",
        "transactions": "integer", "sales_usd": "number", "is_forecast": "boolean"},
        ("ts_hour", "visitors", "transactions", "sales_usd", "is_forecast"),
        "Hourly store totals. Today and future rows are forecasts; earlier days are historical. No SKU sales, sales targets, margin or labor-cost data."),
    "loss": Resource("shrink_events", "shrink", {**PRODUCT, "event_id": "text", "event_type": "text",
        "qty": "integer", "value_usd": "number", "event_ts": "timestamp", "day": "date"},
        ("event_id", "product_name", "event_type", "qty", "value_usd", "event_ts"),
        "Recorded damage, unknown_loss, adjustment and return_anomaly. Units and event count differ. Records do not establish theft or blame.", True, True),
    "feedback": Resource("guest_feedback", "feedback", {"feedback_id": "text", "submitted_at": "timestamp",
        "day": "date", "rating": "integer", "topic": "text", "comment": "text"},
        ("submitted_at", "rating", "topic", "comment"), "Dated guest feedback with ratings and topics; no guest identity."),
    "reviews": Resource("reviews", "reviews", {**PRODUCT, "review_id": "text", "rating": "integer",
        "title": "text", "body": "text", "skin_type": "text", "created_at": "timestamp"},
        ("review_id", "product_id", "product_name", "rating", "title", "body", "skin_type", "created_at"),
        "Catalog-wide product reviews for products carried by this store (present in inventory records, including zero stock), not this store's guest feedback. "
        "rating is the individual 1–5 review; rating_avg/rating_count are catalog aggregates, not aggregates of the filtered review set. "
        "skin_type is the reviewer's stated type; skin_types describes catalog suitability. Individual experiences do not establish clinical suitability or equivalence.", True),
    "deliveries": Resource("replenishment", "replenishment", {**PRODUCT, "expected_at": "timestamp", "qty": "integer", "status": "text"},
        ("product_id", "product_name", "expected_at", "qty", "status"),
        "Scheduled, in_transit, received or delayed replenishment. A past expected time on a delayed record is not a new ETA.", True),
    "roster": Resource("associates", "associates", {"associate_id": "text", "first_name": "text", "role": "text",
        "skills": "text", "shift_start": "timestamp", "shift_end": "timestamp", "current_task": "text"},
        ("associate_id", "first_name", "skills", "shift_start", "shift_end", "current_task"),
        "Shift roster and skill tags, not credentials. Current task alone is not complete availability: assignments, breaks and protected coverage are separate sources."),
}

ENUM_FIELDS = {
    "bopis_orders": {"status": fixtures.BOPIS_STATUSES},
    "store_tasks": {"status": fixtures.TASK_STATUSES, "task_type": fixtures.TASK_TYPES,
                    "source": fixtures.TASK_SOURCES},
    "shrink_events": {"event_type": fixtures.SHRINK_EVENT_TYPES},
    "guest_feedback": {"topic": fixtures.FEEDBACK_TOPICS},
    "replenishment": {"status": fixtures.REPLENISHMENT_STATUSES},
    "associates": {"role": fixtures.ROLES},
}


def _allowed_values(spec):
    values = dict(ENUM_FIELDS.get(spec.table, {}))
    if spec.product_join:
        values["category"] = ("skincare", "haircare", "bath", "fragrance", "makeup")
    return values


def _identity(context, store_id=""):
    state = context.state if context else {}
    home, role, user = state.get("user:store_id"), state.get("user:role"), state.get("user:user_id")
    if not home or not user or role not in {"associate", "store_manager", "district_manager"}:
        raise ValueError("Sign in before reading store records.")
    if store_id and store_id != home and role != "district_manager":
        raise PermissionError("This session can read only its signed-in store.")
    return store_id or home, role, user


def describe_store_data(resource: DiscoveryResource = "", tool_context: ToolContext | None = None) -> dict:
    """Discover queryable operational resources, field types and data limitations; contains no records.

    Empty resource lists available domains. A named resource returns its complete field
    schema and allowed enum values for query_store_data. Query fields, filters,
    grouping, measures and ordering apply to either answer pages or report delivery.
    Reports display matching rows in a searchable table with CSV download; the model
    receives metadata only. Reports have a 5,000-row cap and explicit completeness.
    """
    try:
        _, role, _ = _identity(tool_context)
        available = {k: v for k, v in RESOURCES.items() if not v.manager_only or role != "associate"}
        if resource and resource not in RESOURCES:
            return err("Unknown resource.", code="invalid_resource", available_resources=list(available))
        if resource and resource not in available:
            return err("This resource requires a manager role.", code="forbidden")
        names = [resource] if resource else list(available)
        return ok([{"resource": name, "description": available[name].note,
                    **({"fields": available[name].fields, "default_fields": available[name].default_fields,
                        "allowed_values": _allowed_values(available[name])} if resource else {})}
                   for name in names], as_of=NOW.isoformat(),
                  query_rules="Filters are ANDed; values are strings converted to the field type. Exact enum filters must use an allowed value (case-insensitive); unsupported values are errors, not evidence of zero records. Measures return operation_field (count_records for count without field). Select group fields when using measures. Pages report total_matching; an incomplete page is not the complete result. skin_types and key_ingredients are nullable comma-separated catalog text; rating_avg and rating_count are catalog review aggregates, not review text.",
                  delivery_modes={"answer": "1–100 rows per page, with total matching count",
                                  "report": "Same chosen query; first 5,000 rows to the UI table/CSV, metadata only to the model, explicit completeness"})
    except (ValueError, PermissionError) as error:
        return err(str(error), code="forbidden")


def _value(value, kind):
    if kind == "integer":
        return int(value)
    if kind == "number":
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Numeric filters must be finite.")
        return result
    if kind == "boolean":
        if value.lower() not in {"true", "false"}:
            raise ValueError("Boolean filters use true or false.")
        return value.lower() == "true"
    if kind == "timestamp":
        return parse_ts(value).isoformat()
    if kind == "date":
        from datetime import date
        return date.fromisoformat(value).isoformat()
    if len(value) > 500:
        raise ValueError("Filter values must be at most 500 characters.")
    return value


def _plan(spec, fields, filters, group_by, measures, order_by, limit, offset, sid, role, uid, *, bigquery, max_page_size=100):
    if (type(limit) is not int or type(offset) is not int or not 1 <= limit <= max_page_size
            or offset < 0 or len(filters) > 16 or len(measures) > 12):
        raise ValueError("Use 1–100 rows per page, non-negative offset, at most 16 filters and 12 measures.")
    requested = fields or ([] if measures or group_by else list(spec.default_fields))
    for name in requested + group_by + [f.field for f in filters] + [m.field for m in measures if m.field]:
        if name not in spec.fields:
            raise ValueError(f"Unknown field {name!r}. Available fields: {', '.join(spec.fields)}")
    if len(set(requested)) != len(requested) or len(set(group_by)) != len(group_by):
        raise ValueError("Do not repeat selected or grouping fields.")
    if (measures or group_by) and set(requested) - set(group_by):
        raise ValueError("Selected fields must also be group_by fields when aggregating.")
    params = {"scope_store": sid, "page_limit": limit, "page_offset": offset}
    where = ["store_id = @scope_store"]
    if spec.table == "store_tasks" and role == "associate":
        where.append("assignee_id = @scope_user")
        params["scope_user"] = uid
    operators = {"eq": "=", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
    for i, item in enumerate(filters):
        kind, column = spec.fields[item.field], f"`{item.field}`"
        if item.operator == "is_null":
            where.append(f"{column} IS NULL")
            continue
        allowed = _allowed_values(spec).get(item.field)
        if allowed and item.operator in {"eq", "ne"} and item.value.lower() not in allowed:
            raise ValueError(f"Unsupported value {item.value!r} for {item.field}. Allowed values: {', '.join(allowed)}.")
        if item.operator == "contains" and kind != "text":
            raise ValueError("contains applies to text fields only.")
        key = f"value_{i}"
        params[key] = _value(item.value, kind)
        parameter = f"@{key}"
        if bigquery and kind in {"timestamp", "date"}:
            parameter = f"{kind.upper()}({parameter})"
        if not bigquery and kind == "timestamp":
            from datetime import UTC
            params[key] = parse_ts(params[key]).astimezone(UTC).isoformat()
        if kind == "text":
            column, parameter = f"LOWER({column})", f"LOWER({parameter})"
        if item.operator == "contains":
            where.append(f"STRPOS({column}, {parameter}) > 0" if bigquery else f"INSTR({column}, {parameter}) > 0")
        else:
            where.append(f"{column} {operators[item.operator]} {parameter}")
    columns = [f"`{name}`" for name in (group_by if measures or group_by else requested)]
    outputs = list(group_by if measures or group_by else requested)
    for measure in measures:
        if not measure.field and measure.operation != "count":
            raise ValueError("Only count may omit its field.")
        if measure.operation in {"sum", "avg"} and spec.fields.get(measure.field) not in {"integer", "number"}:
            raise ValueError("sum and avg require numeric fields.")
        alias = f"{measure.operation}_{measure.field or 'records'}"
        if alias in outputs:
            raise ValueError("Do not repeat a measure.")
        outputs.append(alias)
        operand = f"`{measure.field}`" if measure.field else "*"
        columns.append(f"{measure.operation.upper()}({operand}) AS `{alias}`")
    if not columns:
        raise ValueError("Select fields or measures.")
    for order in order_by:
        if order.field not in outputs:
            raise ValueError(f"Order by an output field: {', '.join(outputs)}")
    # All output columns are tie-breakers, making page boundaries deterministic.
    ordered = [f"`{o.field}` {o.direction.upper()}" for o in order_by]
    ordered += [f"`{name}` ASC" for name in outputs if name not in {o.field for o in order_by}]
    grouping = " GROUP BY " + ", ".join(f"`{name}`" for name in group_by) if group_by else ""
    query = f"SELECT {', '.join(columns)} FROM scoped WHERE {' AND '.join(where)}{grouping}"
    return query, ", ".join(ordered), params


def _bq_source(backend, spec):
    is_review = spec.table == "reviews"
    expressions = ["@scope_store AS store_id" if is_review else "r.store_id"]
    day_field = {"store_traffic": "ts_hour", "shrink_events": "event_ts", "guest_feedback": "submitted_at"}.get(spec.table)
    for field in spec.fields:
        if field == "assignee_name":
            expr = "a.first_name"
        elif field == "product_name":
            expr = "p.name"
        elif spec.product_join and field in PRODUCT and field != "product_id":
            expr = f"p.{field}"
        elif field == "retail_value_usd":
            expr = "r.on_hand * p.price_usd"
        elif field == "below_reorder":
            expr = "r.on_hand < r.reorder_point"
        elif field == "day":
            expr = f"DATE(r.{day_field}, 'America/Chicago')"
        elif field == "is_forecast":
            expr = f"DATE(r.ts_hour, 'America/Chicago') >= DATE('{NOW.date().isoformat()}')"
        elif field == "skills":
            expr = "ARRAY_TO_STRING(r.skills, ', ')"
        else:
            expr = f"r.{field}"
        expressions.append(f"{expr} AS `{field}`")
    join = f" LEFT JOIN {backend._t('products')} p ON r.product_id = p.product_id" if spec.product_join else ""
    if spec.table == "store_tasks":
        # Group label dimensions before joining: missing or conflicting names stay null,
        # while duplicate dimension records can never multiply task counts.
        join = (f" LEFT JOIN (SELECT product_id, IF(COUNT(DISTINCT name) = 1, MIN(name), NULL) AS name "
                f"FROM {backend._t('products')} GROUP BY product_id) p ON r.product_id = p.product_id"
                f" LEFT JOIN (SELECT store_id, associate_id, "
                "IF(COUNT(DISTINCT first_name) = 1, MIN(first_name), NULL) AS first_name "
                f"FROM {backend._t('associates')} WHERE store_id = @scope_store "
                "GROUP BY store_id, associate_id) a "
                "ON r.store_id = a.store_id AND r.assignee_id = a.associate_id")
    scope = (f"EXISTS (SELECT 1 FROM {backend._t('store_inventory')} membership "
             "WHERE membership.store_id = @scope_store AND membership.product_id = r.product_id)"
             if is_review else "r.store_id = @scope_store")
    return f"SELECT {', '.join(expressions)} FROM {backend._t(spec.table)} r{join} WHERE {scope}"


def _unique_labels(rows, key, label):
    labels = {}
    for row in rows:
        if row.get(label) is not None:
            labels.setdefault(row[key], set()).add(row[label])
    return {identifier: next(iter(names)) if len(names) == 1 else None
            for identifier, names in labels.items()}


def _fake_records(backend, spec, sid):
    from datetime import UTC
    is_review = spec.table == "reviews"
    task_products = (_unique_labels(backend.products, "product_id", "name")
                     if spec.table == "store_tasks" else {})
    task_people = (_unique_labels((a for a in backend.associates if a["store_id"] == sid),
                                 "associate_id", "first_name")
                   if spec.table == "store_tasks" else {})
    carried = {row["product_id"] for row in backend.inventory if row["store_id"] == sid} if is_review else set()
    for original in getattr(backend, spec.fake_attribute):
        if (is_review and original["product_id"] not in carried) or (not is_review and original["store_id"] != sid):
            continue
        row = dict(original)
        if spec.table == "store_tasks":
            row.update(product_name=task_products.get(row.get("product_id")),
                       assignee_name=task_people.get(row.get("assignee_id")))
        if is_review:
            row["store_id"] = sid
        if spec.product_join:
            product = backend._product[row["product_id"]]
            row.update({"product_name": product["name"], **{key: product[key] for key in PRODUCT
                        if key not in {"product_name", "product_id"}}})
        if spec.table == "store_inventory":
            row.update(retail_value_usd=row["on_hand"] * row["price_usd"], below_reorder=row["on_hand"] < row["reorder_point"])
        if "day" in spec.fields:
            time_field = {"store_traffic": "ts_hour", "shrink_events": "event_ts", "guest_feedback": "submitted_at"}[spec.table]
            row["day"] = parse_ts(row[time_field]).astimezone(NOW.tzinfo).date().isoformat()
        if "is_forecast" in spec.fields:
            row["is_forecast"] = row["day"] >= NOW.date().isoformat()
        if "skills" in spec.fields:
            row["skills"] = ", ".join(row["skills"])
        for field, kind in spec.fields.items():
            if kind == "timestamp" and row.get(field) is not None:
                row[field] = parse_ts(row[field]).astimezone(UTC).isoformat()
        yield {key: row.get(key) for key in ["store_id", *spec.fields]}


def _execute(backend, spec, query, ordering, params):
    if backend.name == "bigquery":
        sql = f"""WITH scoped AS ({_bq_source(backend, spec)}), result AS ({query}),
                  page AS (SELECT * FROM result ORDER BY {ordering} LIMIT @page_limit OFFSET @page_offset)
                  SELECT TO_JSON_STRING(ARRAY(SELECT AS STRUCT * FROM page)) AS page_rows_json,
                         (SELECT COUNT(*) FROM result) AS total_matching"""
        output = backend._query(sql, params, tool="query_store_data")[0]
        return json.loads(output["page_rows_json"]), int(output["total_matching"])
    if backend.name != "fake":
        raise ValueError("This backend does not support structured store queries.")
    # Execute the same validated relational plan over test records without emulating its answer.
    backend._log("query_store_data", query=query, parameters=params)
    columns = ["store_id", *spec.fields]
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        kinds = {"integer": "INTEGER", "number": "REAL", "boolean": "INTEGER"}
        declaration = ", ".join(f'"{key}" {kinds.get(spec.fields.get(key), "TEXT")}' for key in columns)
        connection.execute(f"CREATE TABLE scoped ({declaration})")
        connection.executemany(f"INSERT INTO scoped VALUES ({','.join('?' for _ in columns)})",
                               ([row[key] for key in columns] for row in _fake_records(backend, spec, params["scope_store"])))
        count = connection.execute(f"SELECT COUNT(*) FROM ({query})", params).fetchone()[0]
        rows = connection.execute(f"{query} ORDER BY {ordering} LIMIT @page_limit OFFSET @page_offset", params)
        values = [dict(row) for row in rows]
        for row in values:
            for field, value in row.items():
                if spec.fields.get(field) == "boolean" and value is not None:
                    row[field] = bool(value)
        return values, count


def query_store_data(resource: ResourceName, fields: list[str] | None = None, filters: list[RecordFilter] | None = None,
                     group_by: list[str] | None = None, measures: list[Measure] | None = None,
                     order_by: list[RecordOrder] | None = None, limit: int = 25, offset: int = 0,
                     store_id: str = "", delivery: Literal["answer", "report"] = "answer",
                     tool_context: ToolContext | None = None) -> dict:
    """Read or aggregate operational records using a model-chosen query plan.

    Resources: inventory, orders, tasks, traffic, loss, feedback, reviews, deliveries, roster.
    describe_store_data supplies fields and data limitations. Filters are ANDed;
    string values are converted using field types. Measures produce operation_field
    aliases (count_records when field is empty). Grouping/aggregation happens in the
    database across ALL matching records before pagination. No SQL or expressions
    accepted. Store/role access is enforced independently of supplied filters.
    Answer delivery returns a page of 1–100 records. Report delivery displays the
    matching table in the app and returns only its metadata here; it always starts
    at the first row and caps the table at 5,000 rows, independently of limit/offset.
    The report's complete flag states whether every matching row was included.
    """
    try:
        sid, role, uid = _identity(tool_context, store_id)
        if resource not in RESOURCES:
            raise ValueError(f"Unknown resource. Choose from: {', '.join(RESOURCES)}")
        spec = RESOURCES[resource]
        if spec.manager_only and role == "associate":
            raise PermissionError("This resource requires a manager role.")
        if delivery not in {"answer", "report"}:
            raise ValueError("Delivery must be answer or report.")
        # Also validate direct Python callers; tool schemas are not an authorization boundary.
        f = [RecordFilter.model_validate(item) for item in filters or []]
        m = [Measure.model_validate(item) for item in measures or []]
        o = [RecordOrder.model_validate(item) for item in order_by or []]
        backend = data_backend.make_backend()
        page_limit, page_offset = (5000, 0) if delivery == "report" else (limit, offset)
        query, ordering, params = _plan(spec, fields or [], f, group_by or [], m, o, page_limit, page_offset,
                                       sid, role, uid, bigquery=backend.name == "bigquery",
                                       max_page_size=5000 if delivery == "report" else 100)
        rows, total = _execute(backend, spec, query, ordering, params)
        if delivery == "report":
            columns = list(group_by or []) if m or group_by else list(fields or spec.default_fields)
            columns += [f"{item.operation}_{item.field or 'records'}" for item in m]
            report_id = str(uuid4())
            complete = len(rows) == total
            tool_context.state["ui:report"] = {
                "id": report_id, "resource": resource, "title": f"{resource.title()} report",
                "store_id": sid, "as_of": NOW.isoformat(), "columns": columns,
                "rows": rows, "total_matching": total, "complete": complete,
            }
            return ok([], resource=resource, store_id=sid, as_of=NOW.isoformat(),
                      report_id=report_id, row_count=len(rows), total_matching=total,
                      complete=complete, display="report", data_notes=spec.note)
        return ok(rows, resource=resource, store_id=sid, as_of=NOW.isoformat(), total_matching=total,
                  returned_count=len(rows), offset=offset, has_more=offset + len(rows) < total,
                  next_offset=offset + len(rows) if offset + len(rows) < total else None,
                  scope="own_assigned_tasks" if resource == "tasks" and role == "associate" else "store",
                  data_notes=spec.note, query={"fields": (group_by or []) if m or group_by else fields or list(spec.default_fields),
                    "filters": [x.model_dump() for x in f], "group_by": group_by or [], "measures": [x.model_dump() for x in m]})
    except PermissionError as error:
        return err(str(error), code="forbidden")
    except GoogleAPICallError as error:
        return err(f"The store data query failed: {type(error).__name__}", code="source_unavailable")
    except (ValueError, TypeError) as error:
        return err(str(error), code="invalid_query")
