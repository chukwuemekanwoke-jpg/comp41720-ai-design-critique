# ADR-0002: Idempotent processing of update events

- **Status:** Accepted
- **Service / owner:** Indexing Worker / Kezhen Zhang
- **Date:** 2026-10-24; finalised 2026-11-20

## Context

RabbitMQ delivers updates at least once. Worker restarts and delayed messages
can cause duplicates or out-of-order updates. Content can change A → B → A:
the third update is new even though it reuses A's immutable snapshot. Retrieval
must see a complete collection generation throughout each request.

## Options considered

Snapshot-only deduplication incorrectly skips A → B → A. Broker-only
deduplication does not provide our durable processing history. Updating the
live index in place exposes partial builds. Choose durable event deduplication,
per-source ordering and immutable candidates with atomic publication.

## Decision

Use `event_id` for duplicate detection, `source_version` for ordering within a
source, and `snapshot_id` for content reuse. SQLite persists processing attempts,
completed events, passages and source state. Completed duplicates are ACKed;
older/equal source versions cannot replace newer active content.

Validate each event, fetch its immutable snapshot, and verify identity and the
SHA-256 of UTF-8 `clean_text`. Deterministic passage IDs permit restart-safe
upserts and content reuse. Build a candidate separately, carrying forward
unchanged sources.

**A half-built index can never become current through the publication API.**
Only an existing `ready` candidate matching the event's source version and
snapshot can activate. Its base must still match the current generation;
otherwise discard and rebuild it, bounded to three publication attempts per
processing attempt. One SQLite transaction changes generation statuses, source
state, `current_index` and completed-event state. ACK follows commit. Published
views exclude `building`, `ready` and `discarded` candidates. Retrieval reads
the pointer and passages in one read transaction and pins that generation.

Processing failures use durable attempt counts, three attempts by default,
and the current consumer's fixed one-second delay before requeue. Invalid
messages go directly to quarantine. The durable queue defaults to
`studentpath.local.updates`; quarantine is `<work queue>.deadletter`. Publish
the persistent original payload with `mandatory=True` and publisher confirms,
then ACK; failed publication leaves the original unacknowledged for redelivery.

**Dead-letter monitoring is metric only:** inspect quarantine queue depth
(`messages_ready`) through RabbitMQ's management API/UI and correlate the
consumer's JSON `dead_letter` action by event ID when available. Automated alerting and a
dedicated Prometheus exporter are future work.

## Consequences

Duplicate delivery does not republish an index; obsolete updates cannot undo a
newer source version, while A → B → A publishes a new generation reusing A's
passages. Failed builds leave the previous generation available. Retaining
published generations and processing history increases storage; pruning is
future work. SQLite commit and RabbitMQ ACK are separate: redelivery remains
possible, including duplicate quarantine entries after a crash during handoff.

## Verification

[PR #16](https://github.com/chukwuemekanwoke-jpg/comp41720-ai-design-critique/pull/16)
implements publication. `tests/test_indexing_worker.py` covers duplicates,
ordering, reversion, hidden candidates, atomic activation and stale/missing
candidates; `tests/test_indexer_consumer.py` checks confirmed quarantine-before-ACK
ordering and no ACK after failed publication. See the
[storage contract](../indexer-retrieval-storage.md) for the reader interface.
