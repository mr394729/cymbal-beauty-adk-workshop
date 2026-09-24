# Contextual event alerts — implementation outline

Status: design preparation only. The integrated subscriber/worker, deduplication store, notification inbox and chat entry point are not implemented. This document creates no cloud resources, subscriptions, data changes or outbound messages. Current answer quality and latency remain the release priority.

The existing `quickstarts/11-ambient-event-agent` demonstrates a recommendation publisher. It accepts an event-shaped input and publishes through a Pub/Sub tool; it does not establish a working inbound Pub/Sub → authenticated worker → store agent → notification flow. Its fixed OSA example is a reference, not the intended general agent contract.

## User need and example

A recorded stock change affects a product with pickup commitments. The useful question is whether any promised order or planned work is now at risk, given reservations, due times, inbound supply and current tasks. A count change alone is not enough to decide urgency.

Use one bounded example: an existing SKU's observed balance decreases. The agent can establish whether the observation is newer than the inventory record, whether reservations overlap pending demand, whether an inbound line arrives before the relevant promise and whether assigned work already addresses the issue. It can recommend attention or determine that no notification is useful. It must not equate a control signal with a completed stock adjustment.

A demo button publishes the event and shows its acknowledgement/event ID. It does not select the answer, call a fixed scenario response or pretend that a model ran. The model chooses relevant reads from available tools. A second variant changes a dependency, such as inbound timing or an already assigned task, so the result depends on context rather than just the event name.

## Proposed components

| Component | Bounded responsibility |
|---|---|
| Authenticated demo publisher | Accept an allowed synthetic store/SKU and observation, generate or reuse an event ID, publish to the namespace topic and return the publish acknowledgement. Never embed an answer. |
| Pub/Sub topic and subscription | Deliver the immutable event to the configured worker. Delivery can repeat; no exactly-once business-effect claim. |
| Authenticated worker | Verify the delivery identity/audience and configured source/topic, validate schema and allowed store scope, claim a deduplication key and create an event-specific invocation. |
| Event processing record | Persist event ID, source revision, claim/lease, attempt status, invocation ID and notification outcome so retries can resume safely. |
| Scoped ADK invocation | Reason from the event observation and current dependencies, using read-only tools and an explicit automation identity. Do not impersonate a store manager or inherit a browser's session. |
| Notification outbox and inbox | Store a bounded recommendation, supporting source IDs/times, recipients and delivery status. Resolve recipients from trusted store/role mappings; do not use a recipient address supplied by the event. |
| Authenticated chat entry | Open the event's evidence in the recipient's own session. A manager may then request and confirm a supported task action. |

The first UI can poll an authenticated inbox. Existing one-way response streaming remains suitable for the opened conversation. Bidirectional streaming is out of scope.

## Proposed event contract

```json
{
  "schema_version": 1,
  "event_id": "publisher-issued-unique-id",
  "event_type": "inventory_observation_changed",
  "source": "configured-inventory-feed",
  "source_revision": "revision-token",
  "store_id": "permitted-store-id",
  "product_id": "existing-product-id",
  "occurred_at": "source-observation-time",
  "observed_balance": {
    "previous_units": 12,
    "current_units": 5
  }
}
```

These quantities illustrate the schema; they are not deployed fixtures or a prescribed answer. The feed contract must define the balance grain and whether it includes reservations. If it cannot, carry that limitation explicitly. A publisher must either commit a change in an isolated synthetic source before publishing, or identify the message as a new observation whose system record may lag. Publishing alone must not change the agent's claim about stored inventory.

Store scope comes from the verified producer/worker authorization mapping and is checked against the event. An untrusted payload cannot authorize arbitrary store access. Existing human-session role checks are not a ready-made automation permission model; define a read-only service principal policy before connecting the worker.

## Processing and failure behavior

1. Validate delivery identity, payload shape, supported source and allowed store/product scope. Reject malformed or unauthorized messages without model calls.
2. Atomically claim `(namespace, source, event_id)` and record the source revision. A completed duplicate returns its recorded outcome. A live lease prevents parallel processing; an expired lease permits a bounded retry.
3. Establish a trace correlation ID and read the applicable source context. Preserve observation age, current-record version and any disagreement. Independent necessary reads may overlap; no fixed sequence of every available tool is required.
4. Ask ADK for a bounded decision: whether notification is warranted, the affected commitments, concise evidence, uncertainty and permitted optional next steps. No automatic inventory/order update or task creation.
5. Save the decision and outbox entry with a stable notification key. Delivery retries use that key so a worker crash between send and acknowledgement does not create a second business notification. Record a no-notification decision as a completed outcome too.
6. Acknowledge only after a durable terminal outcome. Retry temporary source/service failures within a budget; route exhausted or invalid events to an operator-visible failure path. Do not replace failed evidence with a reassuring answer.

Out-of-order revisions require an explicit rule: compare the event revision/observation time with the latest accepted source record. Retain the audit event, but do not re-alert on a superseded state. Distinct meaningful changes may warrant new notifications; content similarity alone is not a safe deduplication key.

## Bounded first implementation

Keep the first pass to one namespace, one supported event schema and one store's allowed products. Add the publisher and worker separately from the chat route. Reuse the existing scoped read tools through a reviewed automation context; add the explicit machine identity boundary instead of bypassing `_identity` or assigning a human role. Use a durable transactional event/outbox store and the existing authenticated frontend for the inbox. Do not send email or chat-platform messages as part of preparation.

The corresponding notebook section belongs in [notebook 06](../../notebooks/06_governance.ipynb). Its first cells should inspect an event and run offline contract/deduplication checks. Live publishing and cloud setup remain explicit later steps after source, permissions and the selected namespace are reviewed.

## Acceptance evidence before a live claim

- A real publish acknowledgement leads to an authenticated worker invocation, measured ADK trace and one visible inbox notification.
- Repeated delivery of one event ID, concurrent delivery and a retry after a simulated crash yield one notification outcome.
- Wrong identity, wrong audience, wrong store, malformed payload and unrelated recipients fail before data access or model execution.
- Changed pickup/inbound/task context changes the supported decision; unchanged low-impact events can produce no notification.
- New observations, stale stored balances and out-of-order events remain distinguishable; no double subtraction of reservations and pending demand.
- Notification links open only for permitted users; an associate cannot inherit manager-only evidence or actions.
- Source failure and exhausted retries remain visible; no task, stock or order write happens without a separate permitted user action and confirmation.
- Report event-to-notification latency and model/tool calls from recorded spans. Do not present a timer animation as an execution measurement.
