# Connected StudentPath local Docker stack

Validated 31 October 2026 on local branch `codex/docker-product-check`, based on
PR #16 fix commit `f2f3f78`. These integration changes have not been pushed.

## Use the frontend

Open <http://localhost:8088>. In Connection settings, save
`http://localhost:8088` and ask **StudentPath pipeline**. The connection resets
on page reload. The response shows synthetic evidence from the actual published
SQLite generation (`idx-N`), rather than `demo-idx-001`.

Answer runs in `evidence_only` mode. It deliberately returns a degraded response
with source passages and no generated prose. No live immigration guidance or
installed language model is included in this check. The displayed fixture links
identify test source URLs and are not real immigration guidance documents.

The optional `http://localhost:8088/demo` connection still uses the old explicit
in-memory demo and is not the connected pipeline.

## What now runs

Collector fixture → durable outbox → continuous relay → RabbitMQ local queue →
continuous Indexer → persistent SQLite index → read-only Retrieval → Gateway →
Answer → frontend.

Indexer and Retrieval share the `index` Docker volume. Only Indexer writes it;
Retrieval mounts it read-only and opens SQLite with `mode=ro`. Every request
resolves its generation and reads its passages in one transaction. Retained
published versions remain pinnable. Missing databases fail closed rather than
being created, and unpublished candidate versions cannot be retrieved.

The collection timestamp is the oldest indexed source check. It cannot reflect
later unchanged Collector checks that emit no update event.

The local consumer uses `studentpath.local.updates`, independently of the team's
shared queue. Failures retry with the worker's persisted attempt limit. Invalid
or exhausted messages are published persistently to `.deadletter` with publisher
confirms before acknowledging the original. The local prototype uses a fixed
one-second retry pause and reconnects after broker errors. Team deployment should
agree on queue ownership, delayed retry topology and quarantine operations.

## Validation

- Full Python 3.12 Docker suite: **244 passed, 3 optional Ollama tests skipped**.
- SQLite tests cover hidden candidates, retained generations, exact provenance,
  conservative freshness, missing storage, malformed versions, read-only access,
  and publication during an in-flight read.
- Consumer tests cover ACK/requeue/quarantine decisions and failed quarantine
  publication retaining the original message.
- Running integration check passed two source revisions through the continuous
  services; verified old pinned evidence, duplicate suppression, malformed-message
  quarantine, readiness, unsupported questions and actual Gateway evidence.
- Browser displayed `LOCAL_PIPELINE` evidence from SQLite generation `idx-3`.

Reports: `docker-check-results/pytest.xml`, `product-check.json`, and
`browser-connected.png`. The earlier baseline had 229 passing tests and exposed
the two missing connections; the new code adds both locally.

## Start and check

From this checkout:

```powershell
docker compose -f compose.check.yaml build tests
docker compose -f compose.check.yaml up -d --no-build
docker compose -f compose.check.yaml restart web
docker compose -f compose.check.yaml run --rm tests
docker compose -f compose.check.yaml run --rm product-check
```

Restarting nginx refreshes service addresses after backend container recreation.
On first startup, allow time for RabbitMQ and the initial index publication.
The integration check adds synthetic records to the local Collector database.

To change the startup fixture, edit `docker-check/LOCAL_PIPELINE.html`, rebuild,
and rerun the `seed` service. The continuous relay/indexer then publishes its
changed content. `seed` is an explicit collection pass, not a source scheduler.

Stop without deleting Collector or index state:

```powershell
docker compose -f compose.check.yaml down
```

Only nginx publishes a host port, on loopback 8088. RabbitMQ's fixed credentials
are disposable local-check credentials. Collector and index data use named
volumes. The check broker has container-local storage: ordinary stop/start keeps
it, but broker recreation can lose queued messages. Add persistent broker storage
and agree operational recovery before deployment. Other Docker projects are
untouched. Admin uploads/authentication and generated-answer evaluation remain
outside this local integration work.
