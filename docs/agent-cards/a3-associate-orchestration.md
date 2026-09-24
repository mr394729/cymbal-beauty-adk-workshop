# Team coverage

Put available skills against the next deadline.

**User:** Dana · Store manager

**Example journey:** Pickup demand → roster and commitments → coverage options → reviewed assignment

**Connected systems:** Workforce management; task management; order management; traffic

**Decision:** Compare skill, shift, current assignments, protected zones and breaks. An approved assignment changes the next availability read. Workload durations are planning estimates, not promises of completion.

**Tools:** get_shift_roster; get_traffic_and_backlog; get_coverage_requirements; get_pickup_workload; describe_store_data; query_store_data

**Data:** Associates and open store tasks join with traffic/order deadlines and a coverage snapshot containing minimum zones, breaks and workload estimates.

**Evaluation references:** ops-coverage-1..3; test_assignment_changes_next_coverage_recommendation. Verify that a newly assigned associate is no longer recommended as free.

**Role research:** [Store-role research](../../docs/research/store-role-research.md). The connectors and records here belong to Cymbal; the source establishes the operational work, not a customer API contract.

**Workload:** Each order retains its own promise and estimated work. The model can compare different windows and current commitments; total queue size does not imply that all orders share the first deadline.

The journey illustrates a capability. The current request, available evidence and user constraints determine the work; scenario selection does not prescribe a tool sequence.
