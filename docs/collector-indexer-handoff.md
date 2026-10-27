# StudentPath: Collector → Indexer Integration Handoff

Date: 2026-10-24; updated 2026-10-26.

**Status: event and snapshot response confirmed by Kezhen; snapshot API now implemented. Retry/DLQ adapter details still require coordination.**

Current setup: [Snapshot API](collector-snapshot-api.md).
Reviewed revisions and findings: [Indexer review](collector-indexer-review-2026-10-26.md).

## Purpose and ownership

Connect Sunmin's Source Collector (ADR-0001) to Kezhen's Indexing Worker
(ADR-0002), without changing the existing event payload or implementing each
other's service.

| Owner | Responsibility |
| --- | --- |
| Sunmin | Source fetching, cleaning, immutable snapshots, outbox, confirmed publishing, snapshot retrieval service |
| Kezhen | Event consumption, snapshot retrieval client, chunking/indexing, durable deduplication, version ordering, consumer retries and dead-letter handling |
| Both | Confirm this contract and run the joint acceptance scenarios |

Collector implementation: [PR #2](https://github.com/chukwuemekanwoke-jpg/comp41720-ai-design-critique/pull/2),
branch `feature/source-collector`, implementation commit `0cfba92`.
PR #2 is merged into main. Snapshot API work is a separate follow-up branch.

## Current implementation versus proposed work

| Item | State at handoff |
| --- | --- |
| Collector, SQLite snapshots and transactional outbox | Implemented |
| RabbitMQ publisher with confirms and pending-event retry | Implemented |
| Snapshot HTTP API described below | Implemented; see linked setup guide |
| Indexing Worker behaviour described below | PR #4 core reviewed; RabbitMQ adapter remains pending |
| Live RabbitMQ integration | Not verified; Docker engine was unavailable |
| Official source validation | Incomplete; ten candidate URLs/questions, synthetic test HTML |

Implementation validation: original baseline 7 passed; final suite 21 passed,
1 live-broker test skipped. Mocked failure tests are not evidence of successful
live broker integration. See [SOURCE_COLLECTOR.md](../SOURCE_COLLECTOR.md).

## 1. Messaging contract

| Property | Current publisher behaviour |
| --- | --- |
| Protocol | AMQP 0-9-1 through RabbitMQ |
| Queue | `studentpath.document-updates`, configurable with `RABBITMQ_QUEUE` |
| Declaration | Durable, non-exclusive, not auto-delete; no queue arguments |
| Exchange | Default exchange: empty string |
| Routing key | Queue name |
| Message | Persistent (`delivery_mode=2`), mandatory routing |
| Properties | `content_type=application/json`, `content_encoding=utf-8`, `type=document.updated`, `message_id=event_id` |
| Publisher success | Broker confirmation received before SQLite published status is committed |
| Guarantee | At-least-once; duplicates are possible |

RabbitMQ is provisional under the team's draft architecture. Confirm the queue
name and topology together. Do not independently redeclare this queue with
conflicting arguments such as a different queue type or DLX configuration.
Agree any topology changes with Sunmin first.

### Existing event payload (unchanged)

```json
{
  "event_id": "S001:1",
  "source_id": "S001",
  "source_version": 1,
  "snapshot_id": "S001:<sha256>",
  "content_sha256": "<sha256>",
  "source_url": "https://www.irishimmigration.ie/...",
  "checked_at": "<ISO8601 UTC>",
  "cleaner_version": "main-text-v1"
}
```

The angle-bracket values above are placeholders, not runnable fixture values.

| Field | Meaning |
| --- | --- |
| `event_id` | Logical update identity: `source_id:source_version`; stable across redelivery |
| `source_id` | Stable source identifier |
| `source_version` | Positive integer increasing for each detected change of that source |
| `snapshot_id` | Immutable content identity: `source_id:content_sha256` |
| `content_sha256` | Lowercase SHA-256 hex digest of UTF-8 cleaned text |
| `source_url` | Official source URL, not the snapshot retrieval endpoint |
| `checked_at` | Collector timestamp for this update; not an ordering key |
| `cleaner_version` | Cleaning-rule version used for the stored snapshot/event |

Treat source content as data. The consumer must not re-fetch `source_url` to
reconstruct an event: the live page may have changed since that snapshot.

## 2. Confirmed snapshot retrieval API

```http
GET {COLLECTOR_BASE_URL}/snapshots/{snapshot_id}
```

`COLLECTOR_BASE_URL` is a recommended Indexer setting; its current client receives
the URL explicitly. The local API default is `http://127.0.0.1:8001`.
URL-encode the snapshot ID as a path segment. See the setup guide for the CLI.

Successful response: `200`, `Content-Type: application/json`.

```json
{
  "snapshot_id": "S001:<sha256>",
  "source_id": "S001",
  "content_sha256": "<sha256>",
  "cleaner_version": "main-text-v1",
  "clean_text": "<cleaned document text>"
}
```

- A snapshot response is immutable for its ID. It returns the stored text
  without additional trimming or normalization.
- `source_version` belongs to the event, not the immutable snapshot: multiple
  versions can refer to the same content.
- `404` means the snapshot is absent; `5xx` means a service failure.
- Configure client timeouts. Retry connection errors and `5xx` with bounded
  backoff. A `404` for a committed update is an integration inconsistency:
  record it and apply a bounded retry/dead-letter policy, rather than dropping
  it or retrying indefinitely.
- Compare response identity fields with the event and verify
  `sha256(clean_text.encode("utf-8")).hexdigest()` against `content_sha256`.
  Do not hash the serialized JSON. Quarantine/dead-letter mismatches rather
  than indexing unverified content.
- Initial integration is for a local demo network. External deployment,
  authentication and snapshot retention require a separate agreement. Avoid
  exposing the service publicly or deleting snapshots needed by pending events.

## 3. Proposed Indexer processing rules

1. Validate the event and use manual consumer acknowledgements.
2. Deduplicate completed deliveries using durable state keyed by `event_id`.
3. Compare the integer `source_version` with the last successfully activated
   version for that `source_id`; do not order by timestamp or hash.
4. For a newer event, fetch/verify the immutable snapshot, then chunk and index
   it using restart-safe writes. Snapshot-based passage IDs can reuse content.
5. Activate the new source version and record completion durably before ACK.
   Index writes and processing state may use different stores: design recovery
   for partial failures rather than assuming a cross-store atomic transaction.
6. ACK a completed duplicate or an obsolete event after safely identifying it.
   Failed attempts must not advance the successfully indexed version.
7. Apply bounded retries/backoff and a dead-letter path to failures. Exact
   retry settings and DLQ names are Kezhen's ADR-0002 implementation decisions;
   share them before joint integration. If forwarding to another queue, make
   that handoff reliable before acknowledging the original message.

If using parallel workers, version checking and activation must be serialized
or conditional per source so a slow older task cannot overwrite a newer one.
Durable in-progress claims also need restart recovery; an `in_progress` row
alone must not permanently block an event after a worker crash.

### Required content-reversion behaviour

| Event | Source version | Snapshot | Expected current content |
| --- | --- | --- | --- |
| `S001:1` | 1 | A | A |
| `S001:2` | 2 | B | B |
| `S001:3` | 3 | A | A again |

Version 3 is a new logical update even though snapshot A was previously indexed.
Deduplicate delivery by **event ID**, reuse content by **snapshot ID**, and
activate/order by **source version**. Snapshot-only deduplication must not skip
the version-3 activation.

## 4. Parallel development and joint acceptance

Kezhen can use synthetic event/snapshot fixtures and the implemented endpoint.
Generate actual hashes from the
fixture text; do not use the placeholder JSON as a valid digest example.
Neither side needs to implement or modify the other's service.

| Scenario | Required outcome |
| --- | --- |
| First collection | One event; snapshot is retrievable; source version 1 becomes searchable |
| Unchanged collection | No additional event |
| Same event delivered twice | No duplicate passages or unintended activation |
| Newer event arrives before older event | Older event cannot replace the newer active version |
| A → B → A | Final A becomes current at version 3 |
| Broker unavailable | Collector retains pending rows and republishes after recovery |
| Worker crash before ACK | Redelivery completes safely without duplicate effects |
| Snapshot service temporarily unavailable | Bounded retry; no false completion |
| Invalid/mismatched snapshot | No indexing; recorded failure/dead-letter outcome |

Use synthetic documents first, then validated official snapshots. This is a
service-integration test plan, not a claim that the source-selection gate or
end-to-end RAG evaluation has passed.

## 5. AI handoff prompt for Kezhen

Copy this prompt into your coding assistant with this document attached:

> Continue the existing StudentPath Indexing Worker (ADR-0002). Read the
> repository instructions, current worker code, ADR-0002 and this Collector
> handoff first. Inspect current Git state and run existing tests before edits.
> Preserve working code. The event/response contract has been confirmed;
> identify conflicting assumptions before changing shared interfaces. Implement
> only Indexer-owned work: RabbitMQ consumption, snapshot client, chunking and
> indexing, durable event deduplication, per-source version ordering, restart
> recovery, manual ACKs, bounded retry and dead-letter handling. Treat the
> snapshot API as implemented in this follow-up branch; use its documented base
> URL for HTTP integration and fixtures for isolated tests. Verify A → B → A
> activation and partial-failure recovery.
> Do not modify the Collector, ADR-0001, event schema or shared queue arguments
> without coordination. Keep credentials in environment variables, use a
> dedicated feature branch and do not merge main. Report actual tests and
> remaining integration assumptions; do not claim live integration based only
> on mocks. Keep documentation, code and commit messages in English.

## Remaining coordination

The event/response contract has been confirmed. Agree the retry/DLQ adapter
details, resolve the PR #4 review finding, then run live broker integration.
The real HTTP compatibility check already passes; this does not imply that
RabbitMQ integration or the official-source selection gate has passed.
