"""Store-scoped connectors that combine current records with operational source snapshots."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from functools import wraps

from google.adk.tools import ToolContext

from agents.cymbal_store_ops.tools import domain_tools as domain
from agents.cymbal_store_ops.tools.data_backend import err, ok


def concurrent_read(function):
    """Run a blocking read outside ADK's event loop while retaining its tool declaration.

    Use only for reads. Confirmation and state-changing tools run on the invocation thread.
    """
    @wraps(function)
    async def read(*args, **kwargs):
        return await asyncio.to_thread(function, *args, **kwargs)
    return read


def snapshot(system: str, subject: str, tool_context: ToolContext | None, store_id: str = "") -> dict:
    sid, error = domain._scope(store_id, tool_context)
    if error:
        return error
    return domain.make_backend().get_operations_context(store_id=sid, system=system, subject_id=subject)


def get_stock_location(product_id: str, store_id: str = "", tool_context: ToolContext | None = None) -> dict:
    """Recorded stock locations and scan instructions for an exact SKU in the signed-in store.

    Read stock and order demand separately for current quantities; a location record is not a stock count.
    """
    return snapshot("stock_location", product_id, tool_context, store_id)


def get_coverage_requirements(tool_context: ToolContext | None = None) -> dict:
    """Today's required zone coverage, protected work, breaks, labour budget and workload estimates.

    Combine with the current roster and assigned tasks; estimates are not guaranteed completion times.
    """
    return snapshot("coverage", "store", tool_context)


def get_merchandising_work(tool_context: ToolContext | None = None) -> dict:
    """Current merchandising directives: approved fixture, version, timing, workload and stock dependency.

    Fixture capacity is not a directive completion target. Only explicitly recorded
    completion criteria establish whether a display can be finished.
    """
    result = snapshot("directives", "store", tool_context)
    if result.get("status") == "SUCCESS":
        result = deepcopy(result)
        for row in result.get("rows", []):
            for directive in row.get("payload", {}).get("directives", []):
                directive.setdefault("required_units", None)
                criteria = directive.get("completion_criteria")
                has_criteria = criteria is not None and criteria not in ("", [], {})
                has_quantity = directive["required_units"] is not None and directive["required_units"] != ""
                directive["completion_criteria_status"] = "recorded" if has_criteria or has_quantity else "not_recorded"
        result["field_semantics"] = {
            "completion_criteria": "Only explicitly recorded directive criteria apply; shelf capacity does not establish a required quantity.",
            "completion_criteria_status": "not_recorded means completion cannot be established from this directive; recorded means criteria or required_units were supplied, not that work is complete.",
            "required_units": "Recorded directive quantity only; null means unknown, not zero. A qualitative criterion can be recorded without a quantity.",
            "due_time": "Directive deadline on its effective_date, in store local time.",
        }
    return result


def _loss_record_status(result, product_id, tool_context):
    if result.get("status") != "SUCCESS":
        return result
    result = {**result, "record_status": "recorded" if result.get("rows") else "not_recorded",
              "record_count": len(result.get("rows", [])),
              "query_scope": {"store_id": domain._state(tool_context).get("user:store_id"), "product_id": product_id}}
    result["record_semantics"] = "record_count counts snapshot records, not individual checks or events inside them. Their absence does not establish an event count or loss amount."
    return result


def get_loss_controls(product_id: str, tool_context: ToolContext | None = None) -> dict:
    """Recorded equipment and inventory-control checks for a product; findings do not establish loss causes.

    checks[].id identifies the inspection record, not a physical fixture, cabinet or repair ticket.
    """
    _, error = domain._manager_scope("", tool_context)
    if error:
        return error
    result = snapshot("loss_controls", product_id, tool_context)
    if result.get("status") == "SUCCESS":
        result = deepcopy(result)
        for row in result.get("rows", []):
            for check in row.get("payload", {}).get("checks", []):
                check["id_type"] = "inspection_record"
    return _loss_record_status(result, product_id, tool_context)


def get_learning_options(associate_id: str = "", tool_context: ToolContext | None = None) -> dict:
    """Completed learning and available short activities. Associates can access only their own learning."""
    from agents.cymbal_store_ops.tools.personal_tools import resolve_coaching_person
    person, error = resolve_coaching_person(associate_id, tool_context)
    if error:
        return error
    result = domain.make_backend().get_operations_context(
        store_id=person["store_id"], system="learning", subject_id=person["associate_id"])
    if result.get("status") == "SUCCESS":
        result["associate"] = person
    return result


def get_loss_reconciliation(product_id: str, tool_context: ToolContext | None = None) -> dict:
    """Reconcile recorded loss events with their inventory movements and open evidence questions.

    Managers only. Distinguish returns, damage, adjustments and unknown loss; the ledger is not proof of theft.
    """
    if domain._state(tool_context).get("user:role") not in {"store_manager", "district_manager"}:
        return err("Loss reconciliation is available to managers.", code="forbidden")
    return _loss_record_status(snapshot("loss_reconciliation", product_id, tool_context), product_id, tool_context)


def get_guest_product_options(query_text: str = "", fragrance_free: bool | None = None,
                              max_price: float = 0.0, category: str = "", skin_type: str = "",
                              tool_context: ToolContext | None = None) -> dict:
    """Find products matching a guest's need and show current store stock for the three best matches.

    Use category for skincare, haircare, bath, fragrance or makeup; query_text is a product/brand/need,
    not a category filter. Use fragrance_free=True only when requested; omit for any.
    The result shows three products at most; `matching` is how many products in the whole catalog qualify, so say
    "three of the seventy" rather than "three" when more qualify. Product claims come from the catalog. Never
    select a substitute for a pickup order without authorization.
    """
    sid, error = domain._scope("", tool_context)
    if error:
        return error
    result = domain.search_products(query_text=query_text, fragrance_free=fragrance_free, max_price=max_price,
                                    category=category, skin_type=skin_type, limit=3)
    if result.get("status") != "SUCCESS":
        return result
    matching = result["total_matching"]  # the catalog count, not the page: the search reports it whatever the limit
    products = result["rows"]
    backend = domain.make_backend()
    def read_stock(product):
        return backend.check_store_stock(product_name=product["product_id"], store_id=sid)
    with ThreadPoolExecutor(max_workers=3) as pool:
        stocks = list(pool.map(read_stock, products))
    rows = []
    for product, stock in zip(products, stocks, strict=True):
        if stock.get("status") != "SUCCESS":
            return stock
        rows.append({"product": product, "stock": stock["rows"]})
    return ok(rows, shown=len(rows), matching=matching, more_qualify=matching > len(rows))
