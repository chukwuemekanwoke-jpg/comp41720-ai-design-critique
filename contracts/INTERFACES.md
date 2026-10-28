# Proposed synchronous service contracts

Status: **proposal for team review**, not implemented or approved. Keep these distinct from the existing Gateway public stub and PR #6 Answer Service implementation.

## Gateway → Retrieval API (proposed)

`POST /v1/retrieve`

Request: `{"request_id":"abc123","question":"Stamp 1G requirements?","top_k":5,"index_version":null}`

Response: `{"request_id":"abc123","index_version":"idx-001","last_success_at":"2026-10-27T12:00:00Z","passages":[{"passage_id":"p-1","source_id":"S001","snapshot_id":"S001:<sha256>","source_version":1,"url":"https://www.irishimmigration.ie/...","text":"...","score":0.83}]}`

Rules: pin a single committed index version per request; preserve official source provenance; empty passages are valid; no guessed evidence. Define version-not-found and unavailable-index error responses before integration.

Retrieval prototype: [implementation and run instructions](../docs/retrieval-api.md).
The standalone endpoint now implements this proposed shape against an injectable
repository; this does not mark the team contract approved. It defines 400
`invalid_request`, 404 `index_version_not_found` (no silent fallback), and 503
`index_unavailable`, each with `request_id`, `error`, and `message`. Scores are
distinct keyword coverage in [0, 1], with passage ID as a deterministic tie-break.
SQLite schema/version mapping and production passage IDs remain open with Kezhen.

## Gateway → Answer Service (alignment proposal)

Gateway forwards `request_id`, `question`, the retrieved passages with full source metadata, `index_version`, and `last_success_at`. The Answer Service returns a status from `answered|insufficient_evidence|degraded`, answer or null, checklist, and citations restricted to supplied passage identifiers. Gateway attaches canonical official URLs and the public response envelope.

**Do not implement this proposal without comparing against PR #6 `docs/answer-service.md` and obtaining Jordan's sign-off.** Decide citation identifiers, field names, model metadata, deadline, and error mapping together. The Answer Service must never invent citations.

## Open decisions

- Canonical passage ID format and score interpretation.
- Gateway→Retrieval and Gateway→Answer HTTP paths and exact Pydantic field mapping.
- Timeout budgets, upstream errors, retries, and whether retrieval returns freshness per source.
- Version-not-found handling and index-activation atomicity.
