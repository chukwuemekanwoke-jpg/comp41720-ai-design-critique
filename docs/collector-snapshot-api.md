# Collector Snapshot API

The event and five-field response contract were confirmed by Kezhen in the team
discussion on 2026-10-24. This implementation returns stored snapshots without
re-fetching the live page or cleaning its text again.

## Run locally

From the repository root in a Python virtual environment:

```powershell
python -m pip install -r requirements-dev.txt
python -m source_collector --manifest data/demo_manifest.json --db collector.sqlite3 --fixture-dir demo_pages
python -m source_collector.snapshot_api --db collector.sqlite3 --host 127.0.0.1 --port 8001
```

Keep the API terminal running during integration. Create the Collector DB first.
Startup fails for a missing database or missing snapshot schema; it never
creates or migrates a database. Each request opens a read-only SQLite connection
to the same local store used by collection and the relay. Do not replace the DB
while serving it. `--db` defaults to `COLLECTOR_DB`, then `collector.sqlite3`.
Relative paths resolve from the process working directory. The default host is
`127.0.0.1` and default port is 8001.

## Connect the Indexer

```python
client = CollectorSnapshotClient(base_url="http://127.0.0.1:8001")
```

`COLLECTOR_BASE_URL=http://127.0.0.1:8001` is the recommended worker environment
setting. PR #4's core currently receives `base_url` explicitly; its future entry
point must read that variable. Kezhen owns that wiring.

For containers, agree a network address separately: container-local loopback
does not reach the host API. No Collector container, public deployment or
authentication is added here. Keep the default loopback binding for the local
demo; use `--host 0.0.0.0` only deliberately on a trusted integration network.
The shared RabbitMQ topology and Compose file are unchanged.

## Endpoint

```http
GET /snapshots/{snapshot_id}
```

URL-encode the ID as one path segment (`S001%3A<64-lowercase-hex-digest>`).
Kezhen's client already uses `quote(snapshot_id, safe="")`.

```json
{
  "snapshot_id": "S001:<sha256>",
  "source_id": "S001",
  "content_sha256": "<sha256>",
  "cleaner_version": "main-text-v1",
  "clean_text": "<exact stored cleaned text>"
}
```

These are placeholders; obtain a real snapshot ID from the CLI or event. The
response contains exactly these five fields, without raw HTML or mutable source
state. Newlines and Unicode are preserved after JSON decoding. Verify the hash
of the decoded text's UTF-8 bytes, not the JSON encoding. `source_version` stays
in the event, because multiple source versions can reuse one snapshot.

| Status | Meaning |
| --- | --- |
| 200 | Stored snapshot with matching identity and verified hash |
| 400 | Malformed ID |
| 404 | Well-formed ID not present |
| 500 | Stored snapshot failed identity/hash verification |
| 503 | Database cannot be opened/read, including lock timeout |

Errors use `{"detail":"..."}` without DB exception details. Read-only mode
is not SQLite `immutable=1`: new committed snapshots remain visible. An old ID
returns the same content after updates, reversion and restart. There is no
snapshot deletion endpoint.

## Validation

```powershell
python -m pytest -q -p no:cacheprovider --basetemp=.test-tmp-api-suite
python scripts/verify_snapshot_client.py --indexer-root <PR4-checkout> --work-dir .test-tmp-contract
```

API tests cover exact fields, encoded IDs, Unicode/hash preservation, historical
snapshot stability, reversion/restart, malformed/missing IDs, read-only access,
missing/wrong DB startup failure, unavailable/corrupted stores, parallel reads
and environment configuration.

On 2026-10-26 the complete main-based API branch suite passed **41 tests**, with
**1 live RabbitMQ test skipped**. The 14 new API cases all passed. The installed
Starlette version emits an httpx TestClient deprecation warning; no test fails.

The compatibility script starts/stops a temporary loopback HTTP server and uses
the unmodified PR #4 client/core. Actual HTTP retrieval, hash verification,
A → B → A activation, passage reuse and duplicate handling passed against PR #4
revision `a59df322a1db6799daea3e3daaef45abef053d69`. This does not verify RabbitMQ,
embeddings or official-source accuracy. See [the PR review](collector-indexer-review-2026-10-26.md)
for the separate multi-source concurrency issue and reproduction instructions.
