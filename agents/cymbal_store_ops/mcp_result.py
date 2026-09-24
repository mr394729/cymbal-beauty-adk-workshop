"""Shared decoding for actual operational MCP response evidence."""
import json

MCP_READ_NAMES = {
    "store_mcp_describe_store_data": "describe_store_data",
    "store_mcp_query_store_data": "query_store_data",
    "store_mcp_search_store_products": "search_products",
    "store_mcp_get_product_details": "get_product_details",
    "store_mcp_get_product_stock": "get_product_stock",
    "store_mcp_get_store_inventory_summary": "get_store_inventory_summary",
}


def normalize_tool_result(name: str, raw: dict) -> dict:
    """Decode the six configured operational MCP tools; retain native contracts."""
    if name not in MCP_READ_NAMES:
        return raw
    value = raw.get("structuredContent") or raw.get("structured_content")
    if raw.get("isError") or raw.get("is_error"):
        return {"status": "ERROR", "error_details": "MCP tool returned an error."}
    if isinstance(value, dict):
        return value
    for part in raw.get("content") or []:
        if part.get("type") == "text":
            try:
                parsed = json.loads(part.get("text", ""))
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, dict):
                return parsed
    return {"status": "ERROR", "error_details": "MCP response contained no structured result."}
