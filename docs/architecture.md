# StudentPath architecture (draft)

Draft service split for the COMP 41720 Option B brief. Owners are not yet
assigned and the fifth service is a proposal for the group to confirm.

## Services and ADRs

| # | Service | Owner | Candidate ADR (one page) |
| --- | --- | --- | --- |
| 1 | **Source collector**: fetches the 15-25 official ISD pages, snapshots them with a version and last-checked date, and detects changes | Sunmin Lee | **Change detection and snapshot versioning.** Polling versus on-demand fetch, what counts as "changed", and how the last-checked date is stored |
| 2 | **Indexing worker**: takes document updates from a queue, splits them into passages, and builds a versioned searchable index | Kezhen Zhang | **Idempotent processing of update events.** Handling duplicate and out-of-order events, retry limits, and a dead-letter path |
| 3 | **Retrieval API**: finds the relevant passages for a question from a known index version | Chukwuemeka Nwoke | **Consistency during re-index.** Whether users see the old or the new index mid-update, and how each answer pins an index version |
| 4 | **Answer service**: passes passages to a local or simulated model and returns the explanation, checklist, source links and last-check date | Jordan Hennessy | **Model timeout and local fallback.** Timeout and retry policy, the simulated-model fallback, and a generation cap |
| 5 | **Gateway and evaluation** (placeholder): single entry point, metrics export, and the evaluation harness | Chukwuemeka Nwoke (with contributions from all members) | **Observability and answer-quality checks.** Rate, error, latency and cost metrics, plus the 30-40 question evaluation set with injection tests |

## Supporting pieces (not services)

- A message queue between the collector and the indexer, run locally via
  Docker Compose.
- A transactional outbox in the source collector's local store, so a crash between
  saving a snapshot and publishing its update event cannot lose the update
  (ADR-0001).
- A one-command startup script, with a Compose file wiring everything together.
- Synthetic or snapshotted data, so the demo works offline.

## Request and update flow

```
Update path (asynchronous)
  Source collector --> [queue] --> Indexing worker --> versioned index

Question path
  User --> Gateway --> Retrieval API --> Answer service --> cited answer
                           |                  |
                  pinned index version   model, with local fallback
```

## Open decisions

- **Fifth service.** The gateway and evaluation service gives the fifth ADR a
  home and carries the metrics the brief requires. The alternative is to split
  the answer service into a prompt and guardrail service and a model-adapter
  service, which gives the injection tests a natural owner.
- **Four members, five ADRs.** The brief asks for one service and one ADR per
  member, and the report needs five ADRs. Confirm how the fifth is allocated.
- **Queue technology.** Pick one that runs locally with one command, such as
  Redis or RabbitMQ in Docker Compose.
- **Owners.** Assigned: source collector and ADR-0001 to Sunmin Lee; indexing worker and ADR-0002 to Kezhen Zhang; retrieval API and ADR-0003 to Chukwuemeka Nwoke; answer service and ADR-0004 to Jordan Hennessy; gateway and evaluation and ADR-0005 to Chukwuemeka Nwoke, with contributions from all members.
