# ADR-0003: Stale-but-consistent answers

- **Status:** Draft (proposed for the Week 10 ADR check)
- **Service:** Retrieval API
- **Owner:** Chukwuemeka Nwoke
- **Date:** 2026-11-05 (revises the 2026-10-17 draft)

## Context

Retrieval serves one complete, immutable index generation per request. That
keeps answers consistent, but consistency is not freshness. The Collector can
detect that an official page has changed before the Indexer publishes a
generation containing the change, so for that window Retrieval would serve
guidance the system already knows is out of date. A last-checked date on every
answer does not solve this, because users learn to ignore it, and an outdated
requirement can affect a student's immigration status.

## Decision

**1. Atomic switch.** The Indexer publishes a generation only when it is
complete. Retrieval resolves the active generation once per request and reads
all passages from it in one read transaction. Partial builds are never visible,
and a pinned version stays readable after a newer one is activated.

**2. Pending-change rule.** Retrieval polls the Collector's source status
(`GET /sources/{source_id}/status`) and caches it. A source has a *pending
change* when the Collector's `source_version` is greater than that source's
version in the generation being read. If any passage that would go to the
Answer service comes from such a source, the request abstains:

> "The official page *[title]* changed on *[detected_at]* and the update is being
> processed. Check the page directly or ask again shortly."

Questions whose evidence comes only from unaffected sources answer normally.

**3. Fetch errors are not changes.** A source that cannot be fetched is stale,
not changed. It gets the ADR-0001 staleness notice and does not abstain.

**4. Status unavailable.** If cached status is older than 60 seconds, or the
Collector does not know a source (404), Retrieval answers with a general
"freshness could not be confirmed" warning. A Collector outage must not stop
the question path.

**5. Stuck updates.** A change pending for more than 15 minutes is exported as a
metric and raises an alert, because it usually means the event was
dead-lettered. Abstention continues until it is indexed.

## Alternatives rejected

- **Last-checked date only.** Users ignore a date shown on every answer.
- **Warn and answer anyway.** The changed passage may be the very requirement the
  student needs.
- **Answer from unaffected passages only.** Silently incomplete.
- **Block all queries during re-indexing, or fail closed when the Collector is
  unreachable.** Both turn an update-path problem into a question-path outage.
- **Passage-level checking.** More precise but needs old passages mapped to new
  text. Deferred; source-level is the first version.

## Consequences

- Gateway and Answer responses need a reason field for this abstention.
- Each page edit makes that page's questions abstain until indexed. A cleaner
  change alters every hash, so all sources go pending at once; schedule cleaner
  changes away from demonstrations.
- Demonstration: change a fixture, stop the Indexer, ask an affected question
  (abstains with the date) and an unaffected one (answers), restart the Indexer,
  ask again (answers from the new generation).

## What would change our mind

- Abstentions during routine refreshes above 10% of evaluation questions: move to
  passage-level checking.
- Evidence that changed pages rarely alter the passages actually retrieved: a
  specific warning without abstention would be enough.

## Open questions

- A bulk status endpoint, so one poll returns every source consistently.
- Final poll interval, cache limit and stuck-update threshold.
- The abstention reason's name in the Gateway contract.
