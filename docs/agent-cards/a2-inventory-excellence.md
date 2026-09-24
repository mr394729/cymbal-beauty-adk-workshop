# Inventory excellence

Understand stock across the store and fulfil demand.

**User:** Manager and associate

**Example journey:** Inventory question → selected evidence → answer, comparison or report → optional reviewed work

**Connected systems:** Inventory counts and reservations; stock locations; order management; inbound supply; tasks

**Decision:** Match the requested store, category or product scope. Whole-store summaries include healthy stock; flexible queries answer new breakdowns without a predefined scenario. Product decisions distinguish gross stock, reservations, available-to-promise and pending demand. Freshness, location confidence and failed picks determine whether an investigation is useful.

**Tools:** describe_store_data; query_store_data; get_store_inventory_summary; list_store_inventory; get_inventory_context; focused stock, order, location, supply and nearby-stock reads

**Data:** Whole-store counts and paged inventory records; stock/order/supply/task tables; inventory_allocation and stock_location snapshots. The product composite joins independent sources concurrently. A report delivers up to 5,000 matching rows directly to the tablet, with full matching count and completeness; the model receives metadata.

**Product comparisons:** Joined catalog fields include price, fragrance-free status, skin types, ingredients and rating average/count. These fields support compound stock queries and reports chosen for the guest’s constraints. Skin types and ingredients are nullable catalog text, not clinical evidence. The coordinator also has exact-product details and a dated review sample. General review queries support filtered records, aggregates and reports; review text and individual ratings are separate from inventory and catalog rating aggregates. Review scope follows products present in the store’s inventory records, including zero stock, without implying that reviewers visited that store.

**Evaluation references:** ops-inventory-1..3; ops-guest-help-1..3; tests/unit/test_inventory_context.py; tests/unit/test_store_inventory.py; tests/unit/test_store_query.py. Counterfactuals cover stale counts, failed picks, missing reservations, source errors and real read concurrency.

**Role research:** [Store-role research](../../docs/research/store-role-research.md). The connectors and records here belong to Cymbal; the source establishes the operational work, not a customer API contract.

The journey illustrates a capability. The current request, available evidence and user constraints determine the work; scenario selection does not prescribe a tool sequence.
