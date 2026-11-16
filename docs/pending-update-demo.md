# Isolated pending-update system demonstration

This exercises existing Collector, relay, RabbitMQ, Indexer, Retrieval, Gateway
and Answer implementations across real Docker HTTP/AMQP/storage boundaries.
It adds only a separate Compose configuration and demonstration scripts. No
teammate's service implementation is changed. Retrieval's Collector status URL
is set explicitly, which is missing from the older check stack configuration.

## Run

From repository root with Docker Desktop running:

```sh
sh scripts/run_pending_update_demo.sh
```

First use downloads/builds images and installs dependencies, requiring internet.
After images are available, the synthetic workflow makes no external source or
model requests. The project is `studentpath-pending-demo`; its queue, network,
volumes and image are separate from the existing check stack and other projects.
Only Gateway is exposed on loopback port 8091. If that port is occupied, stop
this run and choose a different mapping in this dedicated Compose file.

The canonical source identities use synthetic paths under the official domain
to satisfy Collector's existing allowlist. A supplied fixture fetcher returns
only fictional HTML; no official page is downloaded or factual advice claimed.

## Phases and assertions

| Phase | Changed-source query (`formprobe`) | Unaffected query (`feeprobe`) |
| --- | --- | --- |
| Before | Evidence includes `blue` at Collector's current version | Evidence includes `ten` |
| Indexer stopped; form source recollected | `insufficient_evidence` with pending_source_update, old/new versions and detection date | Still returns its original evidence |
| Indexer resumed | Evidence includes `green` at the new source version and a new index generation; pending refusal cleared | Still returns its original evidence |

Answer is deliberately in `evidence_only` mode. Normal responses are labelled
`degraded` with original evidence and no generated answer. The pending refusal
is `policy-response` / `none`, with no evidence claims. This proves the update
handover, not model answer quality or generated-answer recovery. Lexically
disjoint probe words keep this demo independent of ranking-threshold calibration.

The script starts all required services, checks the baseline, stops only this
project's Indexer, performs the change/check, resumes the Indexer and checks
recovery. A shell trap attempts to restart it after a failed/interrupted pending
check. Services remain running afterwards so responses can be inspected. It
never deletes volumes. Re-running collection can advance logical versions;
assertions use observed versions rather than assuming version 1.

## View and preserve evidence

- Gateway Swagger UI: http://localhost:8091/docs . Use POST /v1/questions with
  `{"question":"formprobe"}` or `{"question":"feeprobe"}`.
- JSON report: `docker-check-results/pending-update/pending-update.json`.
  It contains source status and all six public responses, including request IDs,
  source versions, index versions and pending-update details.
- The results directory is ignored by Git. Copy reviewed synthetic results to
  a dated document/report artifact if needed for submission evidence.

The report's revision is the host Git HEAD used to build. Uncommitted demo files
are not included in that commit; record this distinction until the demo is
committed. Re-run after the pending Answer PRs merge before claiming those
features were checked together in the deployed system.

## Stop without deleting state

```sh
docker compose -f compose.pending-demo.yaml down
```

Do not use `down -v` unless intentionally discarding this demo's state. This
configuration does not add a frontend, metrics dashboard, real source refresh,
Collector-outage/cache-expiry demonstration or broker-restart test. Those are
separate claims requiring separate evidence.
