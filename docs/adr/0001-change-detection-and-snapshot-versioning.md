# ADR-0001: Change detection and snapshot versioning

- **Status:** Draft (proposed)
- **Service:** Source collector
- **Owner:** Sunmin Lee
- **Date:** 2026-10-17
- **Revised:** 2026-10-20 (timestamps and outbox added after team review)

## Context

StudentPath answers from 15-25 official ISD pages that change over time. Every
answer must show the collection version it used and the date the sources were
last successfully fetched. The collector must therefore decide when a page has
changed, keep earlier versions, publish an update event without flooding the
indexer when nothing meaningful changed, and never lose an update that it has
detected.

## Options considered

1. **Scheduled polling with content hashing.** Fetch each source on a timer,
   hash the cleaned text, and emit an event only if the hash differs.
2. **Rely on HTTP validators** (`ETag`, `Last-Modified`). Cheap, but not every
   source sends them reliably, and they change on cosmetic edits.
3. **Manual trigger only.** Simple and deterministic for a demo, but it does
   not show an automatic update path.

## Decision (proposed)

Use scheduled polling with a content hash of the cleaned main text (navigation,
scripts and banners stripped). Keep both the raw fetch and the cleaned text per
snapshot. Offer a manual "check now" trigger so the demo does not wait for the
timer. Each snapshot gets an immutable id (`source_id` plus `sha256` of the
cleaned text).

Each source records two timestamps:

- `last_attempt_at` is updated on every poll, including failed polls. It shows
  that the collector is still trying.
- `last_success_at` is updated only when a fetch succeeds, whether or not the
  content changed. It is the date users see.

When the official site is unavailable, `last_attempt_at` moves and
`last_success_at` stays put, so users can see how old the information is. Once
`last_success_at` passes a staleness threshold, answers show a visible notice
that the source has not been checked recently.

Update events are published through a transactional outbox. The new snapshot
and an outbox row are written in one database transaction. A relay publishes
pending rows and marks each one sent only after the broker confirms. After a
crash, the relay resends anything still pending. Change detection compares each
poll with the last stored snapshot, so without the outbox a crash between saving
and publishing would never be detected again. The outbox closes that gap.

## Consequences

- An unchanged page updates `last_success_at` and produces no update event, so
  there is no needless re-indexing.
- Users can see how current the information is, including during an outage.
- Cosmetic markup changes are ignored, but a text-only edit to a cleaning rule
  changes hashes for every page, so cleaning rules must be versioned.
- Old snapshots are kept, which supports reproducing an earlier answer at the
  cost of storage; a retention limit is needed.
- The outbox adds a small durable table to the collector and makes publishing
  at-least-once. This is safe because the indexing worker is idempotent
  (ADR-0002).
- For the offline demo, snapshots can be replayed from local files.

## Implementation note (2026-10-24)

The collector and separate SQLite outbox relay are implemented in
`source_collector/`. RabbitMQ is the provisional broker, consistent with the
draft architecture; the team still needs to agree its queue contract. The relay
uses a durable queue, persistent mandatory messages and publisher confirms.
It marks published only after confirmation. An event-level SQLite write
reservation serializes competing relays, at the cost of blocking collector
writes during bounded broker operations. Crashes release the lock and roll back
the mark, so retries can duplicate confirmed events. No exactly-once guarantee
is made. Failed publications remain pending and continuous mode retries after a
configurable fixed delay. See `SOURCE_COLLECTOR.md` for configuration, tests and
the snapshot-reversion coordination issue with ADR-0002.

## Snapshot retrieval implementation (2026-10-26)

Kezhen confirmed the event and five-field snapshot response contract. The
Collector now provides read-only `GET /snapshots/{snapshot_id}` through
`source_collector.snapshot_api`. Responses return the exact stored clean text,
content identity and cleaner version, never the latest live page. Read requests
do not write to SQLite; missing stores fail startup instead of creating an empty
database. Identity/hash corruption is reported as an error. Default local demo
address: `http://127.0.0.1:8001`. See `docs/collector-snapshot-api.md` for setup,
error semantics and actual HTTP compatibility validation against PR #4.
Scheduled collection, real-source validation and live broker-to-indexer
integration remain outstanding. No Indexer implementation is changed here.

## Remaining open questions

- Polling interval for the demo versus a realistic interval.
- The staleness threshold before users see a notice.
- How long the relay retries while the broker is down, and whether a long backlog raises an alert.
