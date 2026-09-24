"""The store data reads that go through the MCP server. One list, used by the server and by the agent.

A deployed agent reads store records only through the MCP server (services/store_mcp): the server checks who is
calling and which store they are signed in to, then runs the same read function the agent would run locally.
Writes stay in the agent because ADK's confirmation step (request_confirmation) runs there, and so do the tools
that write into the session (report delivery, the end-of-day dashboard, sign-in, memory).
"""
from __future__ import annotations

from agents.cymbal_store_ops.tools import domain_tools as domain
from agents.cymbal_store_ops.tools import (
    inventory_summary,
    operations_tools,
    personal_tools,
    store_query,
)
from agents.cymbal_store_ops.tools.end_of_day import get_end_of_day_metrics
from agents.cymbal_store_ops.tools.inventory_context import get_inventory_context
from agents.cymbal_store_ops.tools.pickup_workload import get_pickup_workload

READS = {function.__name__: function for function in [
    # store data, catalog and inventory
    store_query.query_store_data, domain.search_products, domain.get_product_details,
    inventory_summary.get_store_inventory_summary, inventory_summary.list_store_inventory,
    inventory_summary.get_product_stock, domain.check_store_stock, domain.find_nearby_stock,
    operations_tools.get_stock_location, domain.get_osa_exceptions, get_inventory_context,
    domain.get_replenishment_status, operations_tools.get_merchandising_work, operations_tools.get_guest_product_options,
    # pickup, team and tasks
    domain.get_bopis_demand, get_pickup_workload, domain.get_shift_roster, domain.get_traffic_and_backlog,
    operations_tools.get_coverage_requirements, domain.get_task_status, domain.get_task_history,
    personal_tools.get_my_work,
    # loss, guests, learning and the day's results
    domain.get_shrink_signals, domain.get_sales_pattern, operations_tools.get_loss_controls,
    operations_tools.get_loss_reconciliation, domain.get_guest_feedback, personal_tools.get_coaching_context,
    operations_tools.get_learning_options, get_end_of_day_metrics,
]}
