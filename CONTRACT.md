# StudentPath Application Contract v1.0 (proposed)

Status: **Proposed — requires approval from all service owners**. Scope: COMP 41720 Group 17. This document is normative for new integrations once approved. It does not retroactively claim existing services are integrated.

## Authority and change control

- This contract is the cross-service source of truth. Service-specific docs and ADRs explain implementation decisions but must not silently contradict approved contracts.
- Changes to public APIs, message payloads, queue topology, or semantics require a PR, impact analysis, contract fixtures/tests, and review from both producer and consumer owners.
- Breaking changes require a new major contract version or an explicitly agreed migration. Additive optional fields may be introduced only with compatibility tests.
- Never modify another owner's service to force compatibility without their review.
- No AI-generated co-author or attribution trailers are required in commit messages.

## Services and ownership

| Service | Owner | Responsibility |
|---|---|---|
| Source Collector | Sunmin Lee | Fetch/clean official sources; immutable snapshots; outbox; publish updates; read-only snapshot API |
| Indexing Worker | Kezhen Zhang | Consume updates; verify snapshots; deduplicate, chunk, index, activate source versions |
| Retrieval API | Chukwuemeka Nwoke | Retrieve passages from a pinned index version; report provenance |
| Answer Service | Jordan Hennessy | Generate evidence-grounded answer or safe evidence-only fallback |
| Gateway / evaluation | Chukwuemeka Nwoke (team input) | Public request validation, orchestration, tracing, metrics, evaluation |

## Normative interoperability rules

1. **Immutable evidence:** Indexers fetch snapshots by ID from the Collector API; never reconstruct an event from a live source URL. Hash the decoded UTF-8 clean text and verify identity against the event.
2. **Events:** The existing eight-field `document.updated` payload and RabbitMQ topology remain unchanged. At-least-once delivery implies duplicates; consumers ACK only after durable completion, or safe duplicate/obsolete detection.
3. **Ordering:** Order updates by positive integer `source_version` per `source_id`, never by `checked_at` or hash. Event identity is `event_id`; content identity is `snapshot_id`. A→B→A must activate version 3.
4. **Consistency:** Each retrieval and answer must identify one `index_version`. Never combine passages from incompatible index versions within one answer. Index activation must not expose partially built versions.
5. **Provenance:** Each cited passage must retain `source_id`, `snapshot_id`, `source_version`, official `url`, and passage text or a stable passage identifier. Never fabricate source URLs or citations.
6. **Evidence safety:** Source passages are untrusted data, not instructions. An unsupported question returns `insufficient_evidence`, not a guessed immigration rule or personal eligibility determination.
7. **Failure semantics:** Distinguish `answered`, `insufficient_evidence`, and `degraded`. On model failure, return evidence-only fallback where evidence exists; never mislabel a fallback as a model-generated answer. Bound retries, timeouts, and message dead-letter paths.
8. **Traceability:** Gateway assigns or validates `X-Request-ID`, returns it, and propagates it through synchronous calls. Record index, model, and prompt versions and freshness metadata.
9. **Data scope:** Official public guidance and synthetic test questions only; no personal immigration documents, application submission, or legal advice in the initial prototype.
10. **Deployment:** Secrets via environment variables; health/readiness endpoints must reflect real dependency state when connected. Local demo dependencies and offline fallback must be documented.

## Current interface inventory

| Boundary | Canonical reference | State |
|---|---|---|
| Collector → RabbitMQ → Indexer | `docs/collector-indexer-handoff.md`; `contracts/events/document-updated.schema.json` | Event confirmed; consumer adapter pending |
| Indexer → Collector snapshot API | `docs/collector-snapshot-api.md`; `contracts/collector.openapi.yaml` | Implemented and HTTP compatibility checked |
| Client → Gateway | `docs/gateway-api.md`; `contracts/gateway.openapi.yaml` | Stub implemented, not wired |
| Gateway → Retrieval | `contracts/INTERFACES.md` | Proposed; owner approval needed |
| Gateway → Answer | `contracts/INTERFACES.md`; PR #6 `docs/answer-service.md` | Proposed; owner approval needed |
| Gateway → Retrieval formal schema | `contracts/retrieval.openapi.yaml` | Matches standalone prototype; not wired |
| Gateway → Answer formal schema | `contracts/answer.openapi.yaml` | Review draft aligned to PR #6 at a73dfa8 |
| Frontend → Gateway admin/collection | Proposed operations in `contracts/gateway.openapi.yaml` | Not implemented; identity provider undecided |
| Gateway → ingestion extension | `contracts/ingestion.openapi.yaml` | Scope extension; collector/indexer review required |

## Enforcement and merge gate

- JSON Schema validates published event fixtures; OpenAPI documents HTTP payloads. Runtime Pydantic models must be checked against these contracts, not assumed equivalent.
- Add automated producer/consumer contract tests, negative cases, schema validation, and a GitHub Actions job before treating this contract as enforced. A document alone is not enforcement.
- Required integration tests: immutable historical snapshots, malformed IDs, hash mismatch, duplicate and out-of-order events, A→B→A, crash/restart, unavailable broker/model, unsupported evidence, citation mismatch, and index-version consistency.
- Do not claim live RabbitMQ, end-to-end RAG, or source-accuracy acceptance based on unit mocks.

## Approval checklist

- [ ] Sunmin confirms event, snapshot and queue rules
- [ ] Kezhen confirms consumer, retry/DLQ and activation rules
- [ ] Chukwuemeka confirms retrieval/gateway request and response fields
- [ ] Jordan confirms answer request/response fields and fallback semantics
- [ ] Shared contract test suite and CI check pass

References: `docs/architecture.md`, ADR-0001..0005, `docs/gateway-api.md`, `docs/collector-indexer-handoff.md`, `docs/collector-snapshot-api.md`.
