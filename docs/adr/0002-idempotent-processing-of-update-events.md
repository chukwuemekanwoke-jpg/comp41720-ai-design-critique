# ADR-0002: Idempotent processing of update events

- **Status:** Draft (proposed)
- **Service:** Indexing worker
- **Owner:** Kezhen Zhang
- **Date:** 2026-10-24

## Context

The Source Collector publishes document-update events through RabbitMQ using
at-least-once delivery. The Indexing Worker may therefore receive duplicate
deliveries, messages after a worker restart, and updates that arrive out of
order.

The Collector assigns three identifiers with different meanings:

- `event_id` identifies one logical update and remains unchanged on redelivery.
- `source_version` is a positive integer that orders updates for one source.
- `snapshot_id` identifies immutable content and may be reused if a page returns
  to content seen previously.

Deduplicating only by `snapshot_id` is incorrect. If a source changes from
A to B and then back to A, source version 3 reuses snapshot A. The worker must
activate version 3 rather than incorrectly leaving version 2 active.

## Options considered

1. **Deduplicate by snapshot ID.** This avoids rebuilding identical content,
   but incorrectly skips a legitimate A → B → A content reversion.
2. **Rely on queue-level deduplication.** This does not reliably survive worker
   restarts, late redeliveries or the queue's deduplication window.
3. **Use separate keys for delivery, ordering and content reuse.** Deduplicate
   by `event_id`, order updates by `source_version`, and reuse indexed content
   by `snapshot_id`.

## Decision (proposed)

Use the three-key approach.

The worker keeps durable processing state keyed by `event_id`. If an event is
already recorded as completed, a repeated delivery is acknowledged and skipped.

For each `source_id`, the worker stores the last successfully activated
`source_version`. An event with an older or equal version cannot replace a newer
active version. `checked_at`, hashes and arrival order are not used for version
ordering.

For a newer event, the worker:

1. validates the event;
2. retrieves the immutable snapshot from the Collector using `snapshot_id`;
3. verifies the response identity and SHA-256 of the UTF-8 `clean_text`;
4. reuses existing passages and search data when the `snapshot_id` has already
   been indexed, or creates them using restart-safe upserts;
5. creates a new immutable index-version manifest;
6. atomically switches the `current_index_version` pointer;
7. records the event as completed durably; and
8. acknowledges the RabbitMQ delivery.

The worker uses manual acknowledgements. A failed attempt must not advance the
active source version or mark the event as completed. Recoverable in-progress
state must not permanently block a redelivered event after a worker crash.

Processing failures use bounded retries with durable attempt tracking and
exponential backoff. The proposed limit is three total processing attempts.
After the final failure, the worker publishes a failure record to a durable
dead-letter queue. The original message is acknowledged only after the
dead-letter handoff is confirmed.

Shared RabbitMQ queue arguments and final retry/DLQ names must be agreed with
the Collector owner before changing the shared topology.

## Consequences

- Repeated delivery of the same `event_id` does not create duplicate effects.
- Out-of-order older events cannot replace a newer active source version.
- A → B → A correctly activates A again as the newest logical version.
- Previously indexed content can reuse passages and embeddings.
- Manual acknowledgement permits safe recovery after a worker crash.
- The worker needs durable processed-event, attempt and per-source-version
  state.
- Index writes and processing state may use different stores, so recovery must
  handle partial failures without assuming one cross-store transaction.
- Poison or inconsistent messages eventually reach the dead-letter queue
  instead of blocking the work queue indefinitely.

## Open questions

- Final retry delays and dead-letter queue name.
- Whether a dead-lettered event produces an alert or only an exported metric.
- Final search/index storage technology.
