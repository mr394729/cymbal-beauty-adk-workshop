# Store manager

Choose the work that matters first.

**User:** Dana · Store manager

**Example journey:** Opening question → parallel evidence reads → ranked decisions → reviewed work

**Connected systems:** Stock and allocations; pickup orders; workforce and tasks; feedback and merchandising

**Decision:** Answer the current request using available capabilities and the user’s constraints. Opening plans use three parallel BriefingSignals code branches followed by a model-written ActionPlan. Selective facts retain quantities, deadlines, ownership and uncertainty; repeated source transcripts are excluded from model input while full events remain in the trace. Other requests use model-selected reads and specialists.

**Tools:** daily_briefing; describe_store_data; query_store_data; get_store_inventory_summary; list_store_inventory; search_products; get_product_details; guest, merchandising and own-work tools; specialist agents and reviewed tasks

**Data:** Structured queries cover inventory, orders, tasks, traffic, loss, feedback, reviews, deliveries and roster. The model selects fields, filters, groups and aggregates; code enforces store and role scope. Reports send matching rows to the tablet and only metadata to the model, with an explicit completeness count and a 5,000-row cap.

**Guest comparisons:** Catalog search and exact-product details support price and attribute comparisons. Details include rating averages and counts plus the latest three dated reviews, identified as a sample with a separate count of all stored reviews. The general reviews resource supports chosen date, rating, skin-type and text filters, aggregates and reports over the existing review records. These are catalog-wide reviews for products carried by the store, including zero-stock products; they are not local guest feedback. Review experiences do not establish suitability or equivalent benefits. Store stock is separate evidence.

**Evaluation references:** ops-opening-1; ops-opening-2; ops-opening-3. Check that the opening plan retains exact quantities, deadlines and current ownership.

**Role research:** [Store-role research](../../docs/research/store-role-research.md). The connectors and records here belong to Cymbal; the source establishes the operational work, not a customer API contract.

The journey illustrates a capability. The current request, available evidence and user constraints determine the work; scenario selection does not prescribe a tool sequence.
