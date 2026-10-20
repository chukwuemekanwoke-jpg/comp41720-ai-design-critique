# ADR-0001: Change detection and snapshot versioning

- **Status:** Draft (proposed)
- **Service:** Source collector
- **Owner:** Sunmin Lee
- **Date:** 2026-10-17

## Context

StudentPath answers from 15-25 official ISD pages that change over time. Every
answer must show the collection version it used and the date the sources were
last checked. The collector must therefore decide when a page has changed,
keep earlier versions, and publish an update event without flooding the
indexer when nothing meaningful changed.

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
cleaned text) and a `last_checked_at` timestamp, which is updated even when the
content is unchanged.

## Consequences

- An unchanged page produces no update event, so no needless re-indexing.
- `last_checked_at` and the snapshot id can be shown to users with every answer.
- Cosmetic markup changes are ignored, but a text-only edit to a cleaning
  rule changes hashes for every page, so cleaning rules must be versioned.
- Old snapshots are kept, which supports reproducing an earlier answer at the
  cost of storage; a retention limit is needed.
- For the offline demo, snapshots can be replayed from local files.

## Open questions

- Polling interval for the demo versus a realistic interval.
- How a fetch failure is recorded without advancing `last_checked_at`.
