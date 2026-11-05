# Source Status API and stale-source handoff (Issue #14, Milestone A)

Updated: 2026-11-04. Owners: Sunmin (Collector), Emeka (Retrieval/Gateway policy),
Kezhen (Indexer). This additive API implements the event/status responsibility
split confirmed in the team's 2026-11-04 discussion. It does not implement
Retrieval abstention or change any Indexer/Answer code.

## Run and upgrade

Use the existing Collector API process and base URL; there is no new service.

```powershell
python -m pip install -r requirements-dev.txt
# Existing store: repeatable upgrade only; no source fetch or message publish.
python -m source_collector.migrate --db collector.sqlite3
python -m source_collector.snapshot_api --db collector.sqlite3 --host 127.0.0.1 --port 8001
```

For a new synthetic demo store, run collection first instead of the upgrade:

```powershell
python -m source_collector --manifest data/demo_manifest.json --db collector.sqlite3 --fixture-dir demo_pages
python -m source_collector.snapshot_api --db collector.sqlite3
```

The migration command requires an existing file and never creates one. Normal
`Collector` startup also applies the migration. The read-only API never does:
old stores keep serving snapshots, but status returns 503 until a writer upgrades
the schema. Restart old Collector writer processes with the new code before
resuming collection; an old writer does not maintain `detected_at`.

The default local base URL is `http://127.0.0.1:8001`; the existing `--host`,
`--port`, `--db` and `COLLECTOR_DB` settings are unchanged. A container must use
the agreed Collector service address, not its own loopback address. No Docker
topology, public exposure, deployment or unmerged PR #17 dependency is added.

## Wire contract

```http
GET /sources/S001/status
Accept: application/json
```

```json
{
  "source_id": "S001",
  "source_version": 3,
  "snapshot_id": "S001:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "detected_at": "2026-11-04T09:00:00+00:00",
  "last_success_at": "2026-11-04T10:00:00+00:00",
  "last_attempt_at": "2026-11-04T10:00:00+00:00",
  "last_error": null
}
```

The digest above is illustrative, not validated official content. All seven keys
are always present. The existing [Collector OpenAPI](../contracts/collector.openapi.yaml)
is extended to version 1.1.0; its snapshot path/schema is preserved.

| Field | Meaning and null semantics |
| --- | --- |
| `source_id` | Stable `[A-Za-z0-9_-]{1,50}` identifier |
| `source_version` | Latest confirmed per-source logical version, integer >= 0; not an index generation or delivery attempt |
| `snapshot_id` | Latest confirmed content identity, mapped from `latest_snapshot_id`; null before first success |
| `detected_at` | Latest confirmed content-change time; null before first success or if legacy history is unverifiable |
| `last_success_at` | Latest successful fetch and clean check, including unchanged content; null before first success |
| `last_attempt_at` | Latest fetch attempt, including failures; null if never attempted |
| `last_error` | Generic safe fetch/clean failure summary; null after success; does not expose stored exception details |

HTTP timestamp strings are timezone-aware ISO-8601 normalized to UTC. Detection
and success times are captured after successful fetching/cleaning; attempt time
is captured before it. An explicit `collect(..., at=...)` is a timezone-aware
deterministic replay/test override. It does not use a request's current time to
fill a missing stored timestamp.

After a first failed fetch, the source returns HTTP 200 with version 0,
`snapshot_id`, `detected_at` and `last_success_at` all null, plus attempt/error
information. This is an unconfirmed source, not a confirmed content change.

| HTTP status | Meaning |
| --- | --- |
| 200 | Valid known source state, including unconfirmed version 0 |
| 400 | Malformed source ID |
| 404 | Source not registered in this store |
| 500 | Inconsistent version/snapshot identity or invalid stored timestamp |
| 503 | Store unavailable, locked beyond read timeout, or missing status migration |

Errors retain the existing `{"detail":"..."}` style. Queries open a read-only
connection and use one SELECT joining the source with its latest snapshot; they
do not fetch, clean, publish, increment a version or write to SQLite.

## Durable detection and migration

`sources.detected_at` is added under an SQLite write reservation after checking
the schema. Concurrent writer startups serialize that check. Existing snapshots,
source IDs/versions and outbox rows remain intact.

For a legacy source lacking `detected_at`, the migration considers only its exact
latest `(source_id, source_version)` outbox row, whether pending or published.
It checks payload event/source/version/snapshot/hash identity and timezone-aware
`checked_at`, then backfills from that timestamp. Missing, invalid or inconsistent
history leaves null. It never substitutes `last_success_at` or a snapshot's first
fetch time: A → B → A may reuse a snapshot first fetched much earlier.

| Collection outcome | Confirmed state | Freshness/error state |
| --- | --- | --- |
| First successful fetch | v1, snapshot and `detected_at`; one event | Success/attempt recorded; no error |
| Unchanged successful check | Version, snapshot, detection and outbox unchanged | Success/attempt timestamps advance; error clears |
| Real changed check | Next version, latest snapshot/detection and one event committed atomically | Success/attempt recorded; error clears |
| A → B → A | v3 reuses A's snapshot with a new detection time/event | Successful check recorded |
| Failed fetch/clean | Version, snapshot, detection and successful timestamp unchanged | Attempt advances; error recorded |
| Broker failure | Source status unchanged | Outbox remains pending; publication status is not index activation |

An outbox/snapshot transaction failure rolls back `detected_at` with the version
and snapshot; the separately recorded attempt remains visible. If old event
history cannot establish a detection time, an unchanged check keeps it unknown;
the next actual change records a new detection timestamp.

## Consumer decisions — Emeka and Kezhen

Emeka: for each source actually used by the retrieved evidence, compare this
API's `source_version` with that source's indexed `source_version`. Do not compare
against the collection-wide `idx-N` index generation. Preserve the pinned index
and its passage provenance while making the comparison.

| Condition | Team policy / consumer action |
| --- | --- |
| Collector version > version used by relevant evidence | Temporarily abstain; identify affected source and detection time when known |
| Versions and snapshot identity agree; fetch healthy | Normal evidence-sufficiency checks |
| Only an unrelated source changed | Do not block the current question |
| Fetch failed/overdue with no newer confirmed version | Freshness warning, not automatic abstention |
| Collector HTTP timeout, 503 or unreachable | Freshness warning, not automatic abstention |
| Unknown source, identity mismatch, or indexed version ahead | Report/monitor an inconsistency; do not silently present it as confirmed current state; coordinate handling with Emeka |

A null legacy `detected_at` does not negate a confirmed higher version: abstain
for affected current-guidance evidence, but state that the detection date is
unknown. For intentionally historical pinned requests, explicitly label the
historical context; Emeka owns the exact response policy in ADR-0003.

The Collector cannot know which index generation is active. It deliberately
returns no `pending`/`indexed` flag and no abstention decision. An outbox row
being published proves neither indexing completion nor readiness for answering.
Kezhen: the eight-field event and five-field snapshot response remain unchanged;
no Indexer event/snapshot client changes are required by this additive endpoint.

### Week 10 ADR-0003 design note for Emeka

- **Decision:** keep atomic complete-index switching; temporarily abstain only
  when relevant current-guidance evidence uses an older confirmed source version.
  Fetch uncertainty/Collector outage produces a warning rather than an assumed
  content change. Show source-specific context and known detection time.
- **Alternatives:** answering from a known outdated source with only a generic
  date does not address confirmed-change risk. Global abstention blocks unaffected
  questions. Treating every fetch error as a change confuses availability with
  freshness and unnecessarily stops answers.
- **Rationale:** distinguish consistent-but-known-outdated evidence from uncertain
  freshness while preserving service availability for unaffected sources.
- **Reconsider when:** measured abstention duration is unacceptable, source-status
  outages dominate, evaluation shows warnings sufficient or unsafe, or the team
  can provide reliable source-specific delta/index completion guarantees.

This note is a handoff, not an edit to Emeka's ADR-0003 implementation.

## Verification and remaining Issue #14 work

```powershell
python -m pip install -r requirements-contracts.txt
python -m pytest -q tests/test_source_status.py tests/test_collector.py tests/test_snapshot_api.py tests/test_relay.py
python scripts/validate_contracts.py
python -m pytest -q
```

On 2026-11-04: affected suite 67 passed; complete Python suite 260 passed and
4 skipped (three opt-in Ollama tests and one opt-in RabbitMQ test). Six OpenAPI
documents validated. Existing Starlette/httpx deprecation warning is unchanged.
Runtime status responses were also checked against the OpenAPI schema; generated
events validated against the unchanged event schema, and the existing snapshot
OpenAPI operation was compared with main and is identical. Frontend checks passed.
These counts do not assert live-model/broker integration or hosted CI success.

Milestone A covers the agreed status contract and detection history. Subsequent
work remains separate: hidden-text ingestion hardening and cleaner-version
compatibility; one-command saved-snapshot/local-fixture-server demonstrations;
permitted official-source validation; real broker/update recovery integration;
Retrieval source-specific abstention wiring; team evaluation, including repeated
trials and model/prompt/index versions. No official-source selection gate or
end-to-end stale-answer demonstration is claimed by this PR.
