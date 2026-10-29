# API contract review pack

Start with [INTERFACES.md](INTERFACES.md) for implementation state and exact
Retrieval → Gateway → Answer field mapping. The specifications are OpenAPI 3.0.3.
Keep the files together: relative references use `common.openapi.yaml`.

| Document | Purpose |
|---|---|
| `gateway.openapi.yaml` | Public REST orchestration and proposed admin/collection operations |
| `retrieval.openapi.yaml` | Current standalone retrieval HTTP interface |
| `answer.openapi.yaml` | PR #6 alignment draft; Jordan's review required |
| `collector.openapi.yaml` | Existing snapshot HTTP API, unchanged |
| `ingestion.openapi.yaml` | Proposed service-authenticated policy ingestion/review/status extension |
| `common.openapi.yaml` | Shared provenance, answer, upload, job and error shapes |

Validate from the repository root:

```sh
python -m pip install -r requirements-contracts.txt
python scripts/validate_contracts.py
```

Validation checks specification structure and references. Runtime cross-field
rules, authorisation, freshness consistency and citation integrity need separate
integration tests before endpoints can be enabled. `x-implementation: proposed`
does not mean a route is implemented. The public question route calls Retrieval
and Answer. Generic error envelopes use `request_id`, `error`, `message`; the existing
collector snapshot errors continue to use FastAPI's `detail` shape.

Proposed Gateway error codes: 400 `invalid_request`, 401 `unauthenticated`,
403 `forbidden`, 404 `not_found`, 409 `conflict`, 413 `payload_too_large`,
415 `unsupported_media_type`, 502 `upstream_unavailable`, 504 `upstream_timeout`.
Keep detailed service error codes internal where appropriate. Proposed collection
503 uses `collection_unavailable`; internal ingestion 503 uses `store_unavailable`.
Preserve the current retrieval-specific errors documented in its specification.

See [the integration plan](../docs/frontend-gateway-integration.md) for auth,
idempotency, job transitions, timeout budgets and ownership decisions.
