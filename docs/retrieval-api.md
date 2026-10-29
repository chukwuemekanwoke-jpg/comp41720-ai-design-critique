# Retrieval API prototype

Implements the Retrieval portion of the proposed `contracts/INTERFACES.md`
and the single-version read in draft ADR-0003. This does not approve either
proposal or integrate the Gateway or Answer Service.

## Run and test

From the repository root:

```sh
python -m pip install -r requirements-dev.txt
python -m uvicorn retrieval_api.app:create_demo_app --factory --port 8001
python -m pytest -q
```

Open `http://localhost:8001/docs`. The explicit demo factory loads synthetic
passages, labelled in their text and using `demo-` identifiers. They are not
official guidance; the official domain is a provenance fixture only. No live
policy pages are fetched. The normal `retrieval_api.app:app` has no configured
repository and returns 503 until an adapter is supplied to `create_app`.

## HTTP contract

`POST /v1/retrieve`:

```json
{"request_id":"abc123","question":"Stamp 1G graduate requirements?","top_k":5,"index_version":null}
```

Returns `request_id`, `index_version`, `last_success_at` (timezone-aware index
timestamp), and `passages`. Each passage carries `passage_id`, `source_id`,
`snapshot_id`, `source_version`, `url`, `text` and `score`, preserving stored
evidence unchanged. No generated answer or invented citation is returned.

`request_id` is required: 1–64 ASCII letters, digits, underscores or hyphens.
The validated body ID takes precedence over `X-Request-ID`; the response header
matches the body. Invalid requests preserve a valid body ID, otherwise a valid
header ID, otherwise a generated ID. Questions are trimmed, 3–500 characters;
`top_k` defaults to 5 and accepts strict integers 1–20. `index_version` is null
or a nonempty string up to 128 characters. Unknown fields are rejected.

Errors use `{"request_id":"...","error":"...","message":"..."}`:

| HTTP | error | Meaning |
| --- | --- | --- |
| 400 | invalid_request | Invalid body or malformed JSON |
| 404 | index_version_not_found | Explicit version is absent or pruned; no fallback |
| 503 | index_unavailable | No active committed index, unconfigured adapter, or storage read failure |

No matches and an empty committed index both return 200 with empty passages.
`GET /healthz` reports process liveness only, not index readiness.
FastAPI generates the endpoint schema at `/openapi.json`.

## Ranking

The baseline case-folds Unicode text, extracts alphanumeric words, removes a
small documented stop-word set (`retrieval_api/search.py`), and deduplicates
query terms. Score = number of distinct query terms present in passage text /
number of distinct query terms. Zero-overlap passages are excluded. Results
sort by descending score, then ascending passage ID, before applying `top_k`.
Scores are lexical coverage, not probabilities or evidence confidence. There
is no stemming, semantic search, phrase matching or policy interpretation.

## Storage boundary and consistency

`PassageRepository.pin(index_version)` returns a frozen `IndexSnapshot` holding
version, freshness and a tuple of frozen passages. Each request calls it once;
ranking uses only that view. The in-memory adapter atomically publishes complete
snapshots, rejects reuse of committed version IDs and supports pointer rollback.
Candidate construction remains outside publication. A request holding an older
view completes against it after activation of a newer version. Tests pause an
in-flight request, activate a new snapshot, and verify old/new evidence and
freshness remain separate.

SQLite is deliberately deferred pending agreement with Kezhen. The adapter must
resolve the active pointer and read all passages and freshness in one consistent
read transaction, preserve index IDs and provenance, exclude incomplete builds,
and translate storage failures to `IndexUnavailable`. Explicit missing versions
raise `IndexVersionNotFound`. Agree schema, integer/string version mapping,
read-only connection configuration, atomic activation, pruning/retention and
`last_success_at` semantics before wiring shared storage. The retrieval package
does not import the indexing worker or assume its tables or file path.

The prototype loads a small snapshot and scans it in memory. Large indexes will
need indexed search behind an agreed repository boundary. No full application
Compose, Gateway or Answer Service integration is included in this milestone.
