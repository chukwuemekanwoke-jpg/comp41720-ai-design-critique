# StudentPath Source Collector — outbox relay milestone

Scope: official ISD collection, immutable snapshots, change detection, SQLite transactional outbox, a separate RabbitMQ relay and a read-only snapshot HTTP API. Scheduling, live source validation and end-to-end RabbitMQ/Indexer integration remain future milestones.

## Setup

```bash
python -m pip install -r requirements.txt pytest
python -m pytest -q
python -m source_collector --manifest data/demo_manifest.json --db collector.sqlite3 --fixture-dir demo_pages
```

Provide demo input files like `demo_pages/S001.html` for offline collection; without `--fixture-dir` the Collector attempts live official fetches (which may be blocked by the ISD server). Snapshots and pending events persist across restarts. Use `--basetemp=.test-tmp` with pytest if the system temporary directory is restricted.

For all project tests, install `requirements-dev.txt`. To serve stored snapshots,
run `python -m source_collector.snapshot_api --db collector.sqlite3`. The default
base URL is `http://127.0.0.1:8001`.
See [Snapshot API setup and contract](docs/collector-snapshot-api.md).

## RabbitMQ demonstration (PowerShell)

Use a project virtual environment. Create an untracked `.env` with your own
`RABBITMQ_USER` and `RABBITMQ_PASSWORD` values. Do not commit credentials.

```powershell
docker compose up -d --wait rabbitmq
# Replace placeholders; percent-encode special characters in URL credentials.
$env:RABBITMQ_URL = 'amqp://<user>:<password>@localhost:5672/%2F'
python -m source_collector --manifest data/demo_manifest.json --db collector.sqlite3 --fixture-dir demo_pages
python -m source_collector.relay --db collector.sqlite3 --once
# Continuous relay, with retry on broker failure:
python -m source_collector.relay --db collector.sqlite3
```

Compose binds AMQP (5672) and the management UI (15672) to loopback only and
stores broker data in a named volume. `.env` configures Compose; the Python
relay reads its process environment and does not load `.env` automatically.
Changing initial broker credentials does not change users in an existing volume.
`docker compose down` stops the demo while retaining messages; `down -v` deletes
broker data and should only be used when intentionally resetting the demo.

| Variable | Default / requirement |
| --- | --- |
| `RABBITMQ_URL` | Required AMQP/AMQPS URL, no embedded default credentials |
| `RABBITMQ_QUEUE` | `studentpath.document-updates` |
| `COLLECTOR_DB` | `collector.sqlite3`, existing collector DB required |
| `RELAY_PUBLISH_TIMEOUT` | 15 seconds, positive, connection/confirmation deadline |
| `RELAY_RETRY_SECONDS` | 5 seconds, positive, delay between batches/retries |

`--limit` bounds a batch (default 100). `--once` exits 0 on success, 1 on
publication/database failure and 2 on configuration failure. Continuous mode
retries indefinitely with a fixed configured delay; it never drops pending rows.
Logs report counts and error types without exposing broker URL credentials.

## Delivery and concurrency policy

The relay declares a durable queue, enables publisher confirms, and publishes
persistent JSON messages with `mandatory=True` through the default exchange.
`message_id` is the unchanged payload's `event_id`. NACKs, unroutable returns,
connection errors and confirmation timeouts leave the row pending. Only a
confirmed publication changes `status` to `published` and sets `published_at`.
`attempts` counts committed attempts; attempts interrupted by crashes roll back.

For this small SQLite prototype, each event is selected under `BEGIN IMMEDIATE`
and the write reservation remains held through publication and the status commit.
Competing relays therefore cannot select the in-flight event. Locks are released
by rollback or process death without lease expiry or stranded claims. This also
briefly blocks collector writes: one event at a time and bounded broker waits
limit the contention. SQLite lock waits default to 10 seconds; continuous mode
retries a busy database. Use a local filesystem, not a network shared SQLite DB.
Higher throughput should replace this with a carefully fenced lease design or
a server database. Each publish uses a fresh connection, favouring simple
recovery over throughput.

Broker confirmation is not a consumer acknowledgement. A crash or database
failure after confirmation but before the SQLite commit causes redelivery with
the same `event_id`. This is **at-least-once**, not exactly-once. The persistent
volume and queue protect ordinary broker restarts, not loss of broker storage.

## Tests and failure demonstration

```powershell
python -m pytest -q --basetemp=.test-tmp
$env:RABBITMQ_INTEGRATION_URL = $env:RABBITMQ_URL
python -m pytest -q tests/test_rabbitmq_integration.py --basetemp=.test-tmp-integration
```

The opt-in test publishes to a unique durable test queue, consumes and validates
the payload/properties, acknowledges it, and deletes only that queue. It skips
without explicit configuration. Unit tests cover outage/restart recovery, NACK,
unroutable return, timeout, competing relay connections, and duplicates after
broker receipt or a failed database mark. For a manual outage demonstration,
stop RabbitMQ, collect a changed fixture, run the relay once (exit 1, pending
retained), restart RabbitMQ, and run again (confirmed, exit 0).

## Contracts to align with Kezhen

Each outbox event contains `event_id`, `source_id`, `source_version`, `snapshot_id`, `content_sha256`, `source_url`, `checked_at`, and `cleaner_version`. `source_version` increases even if the page returns to older content. The `snapshot_id` identifies immutable content, while `source_version` defines ordering. The Indexer retrieves `clean_text` with `GET /snapshots/{snapshot_id}`; Kezhen confirmed the response contract, now implemented in `source_collector.snapshot_api`.

RabbitMQ is provisional and compatible with the draft architecture's queue
options; team agreement on queue name/topology remains outstanding. No indexer
implementation or payload/schema change is introduced. PR #3 corrects the old
snapshot-ID deduplication rule in ADR-0002: distinguish event ordering
from content deduplication, because A → B → A reuses snapshot A with a newer
source version. Deduplicate delivery by `event_id`, compare `source_version` per
source, and reuse stored content by `snapshot_id` so a reversion can become current.

No student personal data is collected. Restrict live sources to official `irishimmigration.ie` HTTPS URLs. `data/` contains candidate source/QA fixtures and **must not be treated as a passed validation gate**.

The included `demo_pages/S001.html` is **synthetic** and is not a real or certified immigration document. For live collection use `--manifest data/sources_manifest_v1.json` without the fixture argument, only where the ISD website permits fetching.
