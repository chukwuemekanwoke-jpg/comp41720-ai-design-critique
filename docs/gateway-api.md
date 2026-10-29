# Gateway REST API

Owner: Chukwuemeka Nwoke. The Gateway now orchestrates HTTP calls to Retrieval
and Answer; it no longer returns canned answers or special question test hooks.
It does not implement administrator authentication or policy ingestion.

## Public operations

| Endpoint | Behaviour |
|---|---|
| `POST /v1/questions` | Validate a question, retrieve once, then answer from the exact evidence |
| `GET /healthz` | Process liveness only |
| `GET /readyz` | Probe a readable retrieval generation and Answer liveness; 503 if unavailable |
| `GET /metrics` | Request count and request-duration summary in Prometheus format |

Send only `{"question":"Which fictional form is required?"}`. Questions are
trimmed, must contain 3–500 characters, and unknown fields/non-string values are
rejected with 400. An optional `X-Request-ID` accepts 1–64 ASCII letters, digits,
underscores or hyphens. Invalid/missing IDs are replaced. The same ID is returned
and passed through both downstream HTTP calls.

The answer envelope preserves `status`, `answer`, `checklist`, `sources`,
`index_version`, `last_success_at`, `fallback_used`, `model` and `notice`.
There is no `stub` field. `answered` has nonblank generated text and citations;
`insufficient_evidence` has no answer/sources/checklist; `degraded` retains the
retrieved evidence without generated claims or checklist items.

## Boundary checks and failures

The Gateway maps `passages[].text` to `sources[].passage`; it does not send
`passage_id`, `score` or a body request ID to Answer. It requests at most five
passages and validates Answer's limits before calling it. Evidence is never
silently truncated. Missing index/storage errors are not interpreted as no matches.

Every response is checked for matching request IDs (header and body), pinned
index, timezone-aware freshness, and exact supplied citation membership. Changed
text, source metadata, invented citations and duplicate citation effects fail
closed. A degraded response must retain all original sources. Equivalent UTC
timestamp spellings (`Z` and `+00:00`) are accepted. These checks do not establish
semantic correctness of a model's claims.

| HTTP / error | Meaning |
|---|---|
| 400 / `invalid_request` | Invalid public question |
| 502 / `upstream_unavailable` | Connection failure, non-200 response, invalid/oversized response, or evidence mismatch |
| 504 / `upstream_timeout` | Per-call or total deadline exceeded |
| 500 / `internal_error` | Unexpected Gateway error, with a safe public message |

HTTP clients are shared for the process lifetime and closed on shutdown.
Redirects and environment HTTP proxies are disabled; responses are limited to
2 MiB per service. No automatic retries multiply model calls. Socket timeouts
are supplemented by actual per-call and overall asyncio deadlines.

## Configuration

| Variable | Default |
|---|---|
| `RETRIEVAL_BASE_URL` | `http://127.0.0.1:8002` |
| `ANSWER_BASE_URL` | `http://127.0.0.1:8003` |
| `GATEWAY_RETRIEVAL_TIMEOUT_SECONDS` | `3` |
| `GATEWAY_ANSWER_TIMEOUT_SECONDS` | `23` |
| `GATEWAY_TOTAL_TIMEOUT_SECONDS` | `30` |
| `GATEWAY_CORS_ORIGINS` | Empty; same-origin usage only |

Service URLs must be HTTP(S) origins without credentials/paths. CORS accepts an
exact comma-separated origin list; wildcards are rejected. Public CORS permits
GET/POST, Content-Type and X-Request-ID, exposes X-Request-ID and does not allow
credentials. It is not administrator access control. The frontend abort is now
35 seconds, longer than the default Gateway total deadline.

## Run locally (PowerShell)

Python 3.11 or later is required for total asyncio deadlines.

Install dependencies from the repository root:

```powershell
python -m pip install -r requirements-dev.txt -r answer_service/requirements.txt
```

Run each command in a separate terminal:

```powershell
python -m uvicorn retrieval_api.app:create_demo_app --factory --port 8002
```

```powershell
$env:ANSWER_GENERATION_MODE = "evidence_only"
python -m uvicorn answer_service.app:app --port 8003
```

```powershell
$env:GATEWAY_CORS_ORIGINS = "http://localhost:8080"
python -m uvicorn gateway.app:app --port 8000
```

```powershell
python -m http.server 8080 --directory frontend/dist
```

Open http://localhost:8080 and set the Gateway address to http://127.0.0.1:8000
using connection settings. Use the exact allowed frontend origin. Synthetic
questions such as `Stamp 1G graduate requirements?` produce evidence-only
responses, not official policy guidance. The normal Retrieval app fails closed
without an adapter; only the explicit demo factory loads synthetic passages.

For generation, follow `docs/answer-service.md` to enable an available local
model. Model availability and semantic quality require their own verification.
Hosted preview deployment is a separate action from this repository change.

## Verification

```powershell
python -m pytest -q tests/test_gateway.py
python scripts/verify_gateway_client.py
```

The smoke script starts three temporary loopback HTTP services, checks fallback,
no matches, request IDs and CORS, and stops its subprocesses. It does not fetch
policies or call a real model. Tests use actual Retrieval/Answer ASGI APIs and
separate simulated transport/model failures, including index activation during
an in-flight request, forged citations and per-call/combined deadlines.

Readiness checks a retrieval data path rather than liveness alone, but Answer
readiness only asserts the service is alive; generation may still degrade to
its supported evidence-only mode. It is not a guarantee of source freshness.
