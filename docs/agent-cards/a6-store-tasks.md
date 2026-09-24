# Store tasks

Review an action and track the result.

**User:** Manager assigns; associate updates their own work

**Example journey:** Proposed action → confirmation → saved task → completion or blocker

**Connected systems:** Task management; signed-in identity; current work and coverage

**Decision:** Managers create and delegate reviewed tasks. Associates confirm completion or report a blocker on their own open work. The user supplies the outcome or blocker; a suggestion does not assert that physical work happened. Preserve the saved task deadline separately from a proposed earlier review time. A blocker remains visible on the open task; subsequent manager reads include it.

**Tools:** create_store_task; delegate_task; get_my_work; complete_my_task; report_my_task_blocker

**Data:** store_tasks is the mutable record. Ownership and store predicates restrict personal writes; task notes hold completion or blocker context.

**Evaluation references:** tests/unit/test_operations_capabilities.py plus ownership/idempotency blocker tests. Verify approval, rejected cross-person writes, retry behavior and subsequent manager visibility.

**Role research:** [Store-role research](../../docs/research/store-role-research.md). The connectors and records here belong to Cymbal; the source establishes the operational work, not a customer API contract.

The journey illustrates a capability. The current request, available evidence and user constraints determine the work; scenario selection does not prescribe a tool sequence.
