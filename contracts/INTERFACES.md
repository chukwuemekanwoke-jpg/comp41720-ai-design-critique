# HTTP interface inventory and Gateway alignment

Status: **team review draft**. REST/JSON is the synchronous transport; RabbitMQ
remains the asynchronous update path. The browser connects only to the Gateway.

| Boundary | Specification | Implementation state |
|---|---|---|
| Frontend → Gateway questions | [Gateway](gateway.openapi.yaml) | REST orchestration implemented; frontend supports configured Gateway origin |
| Gateway → Retrieval | [Retrieval](retrieval.openapi.yaml) | Implemented; reads published SQLite indexes (PR #17) and reports pending sources (PR #21) |
| Indexer SQLite → Retrieval | [Publication storage](../docs/indexer-retrieval-storage.md) | Implemented; Retrieval reads published views read-only (PR #17) |
| Gateway → Answer | [Answer](answer.openapi.yaml) | Implemented; pending-update handover in Answer (PR #20) and Gateway forwarding (PR #21) |
| Indexer → Collector | [Collector](collector.openapi.yaml) | Existing snapshot API; unchanged |
| Retrieval → Collector source status | [Collector](collector.openapi.yaml) | Additive read-only status API; [migration and comparison policy](../docs/collector-source-status.md); Retrieval polling and comparison implemented (PR #21) |
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

## Pending-update handover

The Answer contract includes the optional `abstention` decision implemented in
PR #20. See [the handover examples](../docs/answer-abstention-handoff.md) for
complete request and response bodies. PR #21 coordinates Retrieval detection
and Gateway forwarding; this contract update does not implement those parts.

Gateway supplies `reason: pending_source_update` and affected source IDs, indexed
and latest versions, and required nullable `detected_at`. Answer validates these
against the supplied evidence. A valid decision returns HTTP 200 with
`insufficient_evidence`, a fixed explanation and affected-source URLs under
`abstention`; `answer` is null, `sources` and `checklist` are empty, and no model
is called. Metadata is `policy-response` / `none` and `fallback_used` is false.
Malformed decisions return HTTP 400. An omitted or null decision preserves
normal processing; normal Answer responses omit the extension.

Collector status caching and expiry are Retrieval policy, not Answer behaviour.
The existing `last_success_at` retains its collection-freshness meaning; it is
not the change-detection date.
