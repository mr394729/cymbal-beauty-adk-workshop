"""Whole-store inventory aggregates and bounded SKU drilldowns."""
from __future__ import annotations

from google.adk.tools import ToolContext

from agents.cymbal_store_ops.tools.data_backend import err, ok

INVENTORY_MEASURES = (
    "sku_count", "stocked_sku_count", "on_hand_units", "on_shelf_units", "backroom_units",
    "empty_shelf_sku_count", "out_of_stock_sku_count", "low_stock_sku_count",
)
AVAILABILITY_FILTERS = ("all", "in_stock", "out_of_stock", "empty_shelf", "low_stock")


def summary_result(rows: list[dict], *, store_id: str, category: str = "") -> dict:
    """Format a complete category aggregate; never infer reservation availability."""
    category = category.strip().casefold()
    if not rows:
        return err(f"No inventory records are available for store {store_id}.", code="not_found")
    available = sorted(row["category"] for row in rows)
    selected = [row for row in rows if not category or row["category"].casefold() == category]
    if not selected:
        return err(f"Unknown inventory category {category!r}.", code="invalid_argument", available_categories=available)
    return ok(selected, store_id=store_id, category_filter=category,
              totals={key: sum(row[key] for row in selected) for key in INVENTORY_MEASURES},
              inventory_row_count=sum(row["inventory_row_count"] for row in selected),
              store_inventory_row_count=sum(row["inventory_row_count"] for row in rows),
              category_count=len(selected), quantity_basis="recorded_inventory_balances",
              reservation_data_included=False, available_to_promise_known=False,
              count_definitions={"stocked_sku_count": "on_hand > 0",
                                 "empty_shelf_sku_count": "on_shelf_qty = 0 and on_hand > 0",
                                 "out_of_stock_sku_count": "on_hand = 0",
                                 "low_stock_sku_count": "on_hand < reorder_point; can overlap other counts"})


def page_result(rows: list[dict], *, store_id: str, category: str, query_text: str, availability: str,
                limit: int, offset: int, total_matching: int, available_categories: list[str]) -> dict:
    if not available_categories:
        return err(f"No inventory records are available for store {store_id}.", code="not_found")
    if category and category not in available_categories:
        return err(f"Unknown inventory category {category!r}.", code="invalid_argument",
                   available_categories=available_categories)
    has_more = offset + len(rows) < total_matching
    return ok(rows, store_id=store_id, category_filter=category, query_text=query_text,
              availability_filter=availability, total_matching=total_matching, returned_count=len(rows),
              page_size=limit, offset=offset, has_more=has_more,
              next_offset=offset + len(rows) if has_more else None,
              quantity_basis="recorded_inventory_balances", reservation_data_included=False,
              available_to_promise_known=False)


def validate_page(availability: str, limit: int, offset: int) -> dict | None:
    if availability not in AVAILABILITY_FILTERS:
        return err(f"availability must be one of {AVAILABILITY_FILTERS}.", code="invalid_argument")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        return err("limit must be an integer from 1 to 100.", code="invalid_argument")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return err("offset must be a non-negative integer.", code="invalid_argument")
    return None


def get_store_inventory_summary(category: str = "", tool_context: ToolContext | None = None) -> dict:
    """Whole signed-in store stock totals and category breakdown, optionally one category.

    Counts every store/SKU inventory record; returns aggregates rather than a product row dump.
    Includes SKU counts, shelf/backroom/on-hand units and stock exceptions. These are recorded balances,
    not reservation-adjusted availability. The result contains totals, not individual product rows.
    """
    from agents.cymbal_store_ops.tools import domain_tools as domain
    store_id, error = domain._scope("", tool_context)
    if error:
        return error
    return domain.make_backend().get_store_inventory_summary(store_id=store_id, category=category.strip().casefold())


def list_store_inventory(category: str = "", query_text: str = "", availability: str = "all",
                         limit: int = 25, offset: int = 0, store_id: str = "",
                         tool_context: ToolContext | None = None) -> dict:
    """Read a bounded page of inventory in SKU order, with the complete matching count.

    Filter by category, SKU/name/brand text, or availability: all, in_stock (on_hand > 0),
    out_of_stock (on_hand = 0), empty_shelf (shelf = 0 with stock elsewhere), low_stock (below reorder).
    The next_offset value identifies the next page; each page contains at most 100 rows.
    A page with has_more=true is an incomplete selection, not the whole matching inventory.
    Rows include exact SKU, name, category, brand, price, shelf/backroom/on-hand and reorder point.
    Quantities are recorded gross balances, not reservation-adjusted available-to-promise.
    Only a district manager can explicitly select a store other than the signed-in store.
    """
    from agents.cymbal_store_ops.tools import domain_tools as domain
    state = domain._state(tool_context)
    signed_store, error = domain._scope("", tool_context)
    if error:
        return error
    if store_id and store_id != signed_store and state.get("user:role") != "district_manager":
        return err("You can read inventory only for your signed-in store.", code="forbidden")
    availability = availability.strip().casefold()
    if error := validate_page(availability, limit, offset):
        return error
    return domain.make_backend().list_store_inventory(
        store_id=store_id or signed_store, category=category.strip().casefold(), query_text=query_text.strip(),
        availability=availability, limit=limit, offset=offset)


def get_product_stock(product_id: str, tool_context: ToolContext | None = None) -> dict:
    """Read the signed-in store's recorded shelf, backroom and on-hand balances for one exact SKU.

    This is a quantity lookup, not an allocation investigation. No matching row means the
    inventory record is absent, not that its balance is zero. It makes one scoped data query.
    """
    from agents.cymbal_store_ops.tools.store_query import query_store_data
    if not product_id.strip():
        return err("An exact product_id is required.", code="invalid_argument")
    result = query_store_data("inventory", fields=["product_id", "product_name", "brand", "on_hand",
                              "on_shelf_qty", "backroom_qty", "updated_at"],
                              filters=[{"field": "product_id", "operator": "eq", "value": product_id.strip()}],
                              limit=1, tool_context=tool_context)
    if result.get("status") == "SUCCESS":
        result["record_found"] = bool(result["rows"])
    return result
