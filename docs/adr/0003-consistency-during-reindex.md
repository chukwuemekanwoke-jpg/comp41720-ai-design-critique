# ADR-0003: Consistency during re-index

- **Status:** Draft (proposed)
- **Service:** Retrieval API
- **Owner:** TBD
- **Date:** 2026-10-17

## Context

When a source page changes, the indexing worker rebuilds part of the index.
During that window a user may ask a question. The brief asks us to make
consistency decisions explicit and to test what users see during a delayed
document update. Every answer must also name the collection version it used.

## Options considered

1. **Update the live index in place.** Simple, but a query can read a mix of old
   and new passages from the same source, and the cited version is ambiguous.
2. **Block queries during re-index.** Consistent, but unavailable, and a slow
   re-index becomes an outage.
3. **Versioned, immutable indexes with an atomic pointer swap.** Queries read
   one complete version; the worker builds the next version off to the side.

## Decision (proposed)

Use versioned, immutable index builds with an atomic switch. The worker builds
index version `N+1` separately and, once complete, updates a single "current
version" pointer. The retrieval API reads the pointer once per request and
queries only that version, returning the version id with the passages. The
answer service passes the id through to the response.

This accepts **eventual consistency** between the source and the index: for a
short time after a page changes, answers cite the previous version, and the
response shows that version and its last-checked date so users can see it.
Within one request the view is always consistent.

## Consequences

- No request ever sees a half-built index, and every answer is reproducible
  from its version id.
- Users can briefly receive an answer based on the earlier page; this is
  visible, not hidden, and the delayed-update test can demonstrate it.
- Two versions are stored at once during a swap, so storage and build time
  rise; old versions are pruned after a grace period.
- Rollback is a pointer change back to the earlier version.

## Open questions

- How many past versions to keep.
- Whether to show a "this source has changed since the index was built" notice
  when the collector knows a newer snapshot exists but it is not yet indexed.
