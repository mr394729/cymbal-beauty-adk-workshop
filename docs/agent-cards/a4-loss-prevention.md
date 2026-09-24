# Loss and damage

Reconcile the exception and choose useful follow-up.

**User:** Dana · Store manager

**Example journey:** Loss pattern → linked evidence → control finding → reviewed follow-up

**Connected systems:** Loss events; disposition evidence; task history; sales; asset-protection checks

**Decision:** Select the evidence needed for the manager’s question. Keep event counts, units and values distinct. Linked disposition records describe existing events and are not additional losses. A control finding can justify a reviewed store task without establishing the cause of a loss.

**Tools:** get_shrink_signals; get_task_history; get_sales_pattern; get_loss_controls; get_loss_reconciliation; describe_store_data; query_store_data

**Data:** Shrink events and task history join loss_controls and loss_reconciliation snapshots. Reconciliation records reference existing event IDs.

**Evaluation references:** ops-loss-1..3; test_reconciliation_snapshot_refers_to_existing_events_without_counting_documents_twice. Verify units, values and record links; no invented attribution of wrongdoing.

**Role research:** [Store-role research](../../docs/research/store-role-research.md). The connectors and records here belong to Cymbal; the source establishes the operational work, not a customer API contract.

The journey illustrates a capability. The current request, available evidence and user constraints determine the work; scenario selection does not prescribe a tool sequence.
