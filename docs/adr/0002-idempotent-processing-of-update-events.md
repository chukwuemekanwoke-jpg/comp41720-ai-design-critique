# ADR-0002: Idempotent processing of update events

- **Status:** Draft (proposed)
- **Service:** Indexing worker
- **Owner:** TBD
- **Date:** 2026-10-17

## Context

The collector publishes a document-update event to a queue and the indexing
worker consumes it. Most queues give at-least-once delivery, so the worker will
see duplicates, retries after a crash, and events that arrive out of order. The
brief requires us to inject duplicate events and show recovery, retry limits
and idempotent processing.

## Options considered

1. **Assume exactly-once delivery.** Not achievable with a typical queue, and
   it would fail the injected-failure demonstration.
2. **Deduplicate in the queue only.** Window-based dedup helps but does not
   survive a worker restart or a late redelivery.
3. **Idempotent handler keyed by snapshot id.** Processing the same event twice
   leaves the index in the same state.

## Decision (proposed)

Make the handler idempotent. The event carries the snapshot id from ADR-0001.
Before work starts the worker records `(snapshot_id, status)` in a
processed-events table. A repeated id whose status is `done` is acknowledged and
skipped. Index writes use upsert by passage id (`snapshot_id` plus passage
position), so a retry after a partial failure overwrites rather than duplicates.
For out-of-order events, a snapshot older than the one already indexed for the
same source is recorded and skipped.

Failures are retried a fixed number of times with exponential backoff, then the
event moves to a dead-letter queue with the error attached.

## Consequences

- Duplicate and replayed events are safe, which the failure demo can show
  directly by publishing the same event twice.
- The worker needs a small durable store for processed-event state.
- The retry limit and backoff must be configured and exposed as metrics.
- A poison message cannot block the queue; it ends up in the dead-letter queue
  for inspection.

## Open questions

- Retry count and backoff values.
- Whether a dead-lettered event raises an alert in the demo or only a metric.
