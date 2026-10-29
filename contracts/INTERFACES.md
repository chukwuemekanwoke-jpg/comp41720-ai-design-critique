# HTTP interface inventory and Gateway alignment

Status: **team review draft**. REST/JSON is the synchronous transport; RabbitMQ
remains the asynchronous update path. The browser connects only to the Gateway.

| Boundary | Specification | Implementation state |
|---|---|---|
| Frontend → Gateway questions | [Gateway](gateway.openapi.yaml) | REST orchestration implemented; frontend supports configured Gateway origin |
| Gateway → Retrieval | [Retrieval](retrieval.openapi.yaml) | Matches local prototype; storage adapter pending |
| Gateway → Answer | [Answer](answer.openapi.yaml) | PR #6 merged; Gateway mapping implemented and tested against actual ASGI API |
| Indexer → Collector | [Collector](collector.openapi.yaml) | Existing snapshot API; unchanged |
| Gateway → ingestion extension | [Ingestion](ingestion.openapi.yaml) | Proposal; collector/indexer owner approval required |
| Frontend → admin/collection endpoints | Gateway operations marked `x-implementation: proposed` | No authentication, upload or status backend yet |
| Collector → RabbitMQ → Indexer | [Event schema](events/document-updated.schema.json) | Existing eight-field payload unchanged |

## Gateway mapping to Answer

The previous prose proposal did not match Jordan's implemented request. PR #6
uses `POST /v1/answers`, `sources` rather than `passages`, and `X-Request-ID`
rather than a body request ID.

| Retrieval response | Answer request | Gateway obligation |
|---|---|---|
| `passages[].text` | `sources[].passage` | Rename only; preserve text |
| Source/snapshot IDs, source version, URL | Same fields on each source | Preserve canonical provenance |
| `passage_id`, `score` | Not accepted | Keep in request-local mapping; omit from Answer body |
| `index_version` | `index_version` | Pin once; do not retrieve again to refresh the answer |
| `last_success_at` | `last_success_at` | Preserve timezone-aware timestamp |
| `request_id` | `X-Request-ID` | Propagate the same ID |

Default `top_k=5` fits Answer's maximum of 10 sources. Answer limits evidence to
4,000 characters per passage and 256-character identifiers. Retrieval currently
does not enforce all these bounds. Detect incompatible evidence before calling
Answer; do not silently truncate it. Agree indexer chunk limits with Kezhen.

Answer returns the public envelope without `stub` and cites a subset of supplied
source objects, not passage IDs. Gateway must verify request ID, index version,
freshness and complete source objects against the pinned request-local evidence.
Preserve `insufficient_evidence` refusals. Citation membership does not prove
semantic support for every generated claim.

## Decisions required before wiring

- Jordan: confirm mapping, duplicate source treatment, generation budget and
  failure policy. The PR's default generation deadline is 20 seconds.
- Kezhen: agree chunk limits, index schema, activation and job completion.
- Sunmin: approve upload/review extension, authenticity review and storage.
- Gateway owner: implement identity checks, CORS, orchestration and validation.

Do not change another owner's service to force compatibility. See the
[integration plan](../docs/frontend-gateway-integration.md) for acceptance checks.
