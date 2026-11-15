# Offline Collector refresh demo

From the repository root with Collector dependencies already installed:

```sh
python -m scripts.demo_collector_refresh
```

The command starts a loopback fixture server on an ephemeral port, performs an
explicit collection for each saved synthetic HTML revision, checks the results,
and prints JSON. It creates a fresh temporary SQLite store and cleans it up on
exit; no credentials, shared queues, live ISD requests, or model calls are needed.
The ISD URL in the event is only a synthetic source identity for the allowlist;
the transport always reads the loopback fixtures. The fixtures are not official
immigration guidance.

| Refresh | Expected version | Pending events | Snapshot |
| --- | ---: | ---: | --- |
| A | 1 | 1 | New A |
| A again | 1 | 1 | Same A; successful check time advances |
| B | 2 | 2 | New B |
| A again | 3 | 3 | Reuses A; detection time advances |

The script checks snapshot hashes, reopens the database, injects a publish
timeout and verifies all three events remain pending. A new relay with a
recording publisher then drains the outbox. This mode simulates the publisher;
it does not claim to exercise a live RabbitMQ broker.

## Opt-in RabbitMQ replay

With the existing Docker check images already built/pulled, reuse that setup:

```sh
docker compose -f compose.check.yaml run --rm --no-build tests python -m scripts.demo_collector_refresh --rabbitmq
```

Or run the same Python module with `--rabbitmq` and set
`RABBITMQ_INTEGRATION_URL` to an isolated local RabbitMQ endpoint. In this
mode the script first uses an unavailable loopback port to exercise the real
publisher's connection failure, then retries against the running broker. It
checks confirmed publication, original message IDs/payloads, persistent delivery
mode and an empty outbox. It consumes and deletes only its uniquely named demo
queue. It does not stop a shared broker, clear existing queues or reset volumes.
This checks recovery from connection failure, not broker restart persistence.
The opt-in RabbitMQ integration suite also runs this scenario.

The demo stops at Collector-to-broker delivery. Indexer activation, duplicate
consumption/DLQ, stale-answer behavior and broker restart persistence belong to
the full pipeline demonstration; this command does not validate those scenarios.
