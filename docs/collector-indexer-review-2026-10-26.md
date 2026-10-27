# Collector-facing review of Indexer PRs

Date: 2026-10-26. Reviewer scope: Collector event/snapshot boundary and update
activation. This is not a full Retrieval API or Indexer review, nor a GitHub
approval/merge action. No Indexer or ADR-0002 files were changed here.

## Revisions reviewed

- PR #3: `073092ae8698f8f394f1f692cf81eae9fb3765d0`.
- PR #4: `a59df322a1db6799daea3e3daaef45abef053d69`.
- Collector API branch based on main `0f28b0f`.

## Contract findings

PR #3 correctly separates `event_id` delivery deduplication, `source_version`
ordering and `snapshot_id` content reuse. Its snapshot verification, manual ACK,
three-total-attempt and confirmed dead-letter requirements fit the Collector.
No Collector-contract blocker was found in the ADR change.

PR #4's `DocumentUpdateEvent` accepts the Collector payload. Its
`CollectorSnapshotClient` URL-encodes the ID and requests `/snapshots/{id}`;
`SnapshotResponse.verify_against` verifies the five response fields and exact
UTF-8 content hash. The worker does not fetch `source_url`. Its core handles
sequential duplicates, obsolete events and A → B → A. The queue adapter,
backoff and confirmed DLQ publication are still absent, so ACK decisions in the
core are not evidence of implemented RabbitMQ handling.

The existing work queue's arguments remain unchanged by either reviewed PR.
An Indexer-owned DLQ can be added without conflicting queue declarations.
The proposed adapter should use three total attempts, delayed transient retries,
persistent mandatory DLQ publishing with confirms, and no original ACK if that
handoff fails. This review does not implement the adapter or declare the DLQ.

## Actionable finding for Kezhen: stale candidates can drop other sources [P1]

Location: PR #4 `indexing_worker/store.py`, candidate baseline selection around
lines 652–680 and pointer activation around lines 408–418.

`create_index_version` copies the current manifest at build time, but `activate`
does not check whether that baseline has changed. The per-source version check
does not protect updates to different sources. Interleaved workers can therefore
activate an incomplete manifest and remove successfully indexed sources from
the current searchable collection.

Reproduced with the reviewed PR's actual store/builder:

1. With no active index, build a ready candidate for `S001:1`.
2. Before activating it, build a ready candidate for `S002:1`.
3. Activate the S001 candidate, then the S002 candidate.
4. The current manifest contains S002 but not S001, while `source_state` still
   reports S001 as active. Both events are marked completed.

Observed: `current_index=2`, `S001_still_in_source_state=True`,
`S001_in_current_manifest=False`.

Suggested fix: record each candidate's base index version and reject/rebuild
on a stale baseline using a transactional comparison, or serialize the full
build-to-activation operation globally across worker processes. Per-source
locking alone is insufficient. Add a two-source interleaving regression test.
Single-worker sequential operation does not trigger this scenario, but the
current implementation should not be presented as safe for parallel workers.

## Validation evidence

- PR #4's unmodified checkout: **55 passed, 1 skipped**.
- Updated main baseline, including Gateway: **27 passed, 1 skipped**.
- Collector API unit/HTTP-client results are recorded in this branch's PR and
  `docs/collector-snapshot-api.md`.
- Live RabbitMQ wiring is outside these results; its opt-in test remains skipped
  without a configured broker.

To reproduce the HTTP compatibility check without merging PR #4:

```powershell
git fetch origin pull/4/head:refs/remotes/origin/pr-4
New-Item -ItemType Directory -Path .test-tmp-pr4-review -Force
git archive --format=zip --output=.test-tmp-pr4-review/pr4.zip origin/pr-4
Expand-Archive .test-tmp-pr4-review/pr4.zip .test-tmp-pr4-review/code
python scripts/verify_snapshot_client.py --indexer-root .test-tmp-pr4-review/code --work-dir .test-tmp-contract
```

This script uses actual loopback HTTP and the unmodified Indexer client and core;
it does not use RabbitMQ or validate official immigration content.
