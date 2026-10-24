# Gateway API (placeholder contract)

Owner: Chukwuemeka Nwoke. Status: draft stub for the group to review.

The gateway is the single entry point for a student's question. It assigns a
request id, calls the retrieval API and the answer service, and returns one
cited answer. It also exports the metrics described in
[ADR-0005](adr/0005-observability-and-answer-quality-checks.md).

The stub in [`gateway/app.py`](../gateway/app.py) implements this contract with
canned data and calls no other service. Other services and the evaluation
harness can be written against it now.

## Endpoints

| Method and path | Purpose |
| --- | --- |
| `POST /v1/questions` | Ask one question, get one cited answer |
| `GET /healthz` | Liveness: the process is up |
| `GET /readyz` | Readiness: reports each dependency (not connected in the stub) |
| `GET /metrics` | Prometheus text: request count by path and status, request duration |

## Ask a question

Request:

```json
{ "question": "Where are the requirements for moving from Stamp 2 to graduate Stamp 1G?" }
```

`question` is 3 to 500 characters. Send an optional `X-Request-ID` header
(letters, digits, `_`, `-`, up to 64 characters). Without a valid one the gateway
makes its own. The same id comes back in the `X-Request-ID` response header and
in the body, and is passed to every downstream call so one question can be
traced end to end.

Response, `200`:

```json
{
  "request_id": "9f2c...",
  "status": "answered",
  "answer": "...",
  "checklist": ["..."],
  "sources": [
    { "source_id": "S001", "snapshot_id": "S001:<sha256>", "source_version": 3,
      "url": "https://www.irishimmigration.ie/...", "passage": "..." }
  ],
  "index_version": "<id>",
  "last_success_at": "2026-10-24T09:00:00+00:00",
  "fallback_used": false,
  "model": { "name": "<model>", "prompt_version": "<id>" },
  "notice": "Information only. This is not an eligibility decision or legal advice.",
  "stub": true
}
```

`stub` is `true` only in the placeholder and goes away with the real service.

### Status values

| `status` | Meaning | `answer` | `sources` |
| --- | --- | --- | --- |
| `answered` | Model answered from retrieved evidence | text | one or more |
| `insufficient_evidence` | Nothing relevant was retrieved; the system does not guess | `null` | empty |
| `degraded` | Model unavailable; the local fallback returned evidence only (ADR-0004) | `null` | one or more |

Every `answered` and `degraded` response names the index version and the
`last_success_at` date, so users can see how current the evidence is (ADR-0001,
ADR-0003).

### Errors

All errors have the same shape and keep the request id:

```json
{ "request_id": "9f2c...", "error": "invalid_request", "message": "..." }
```

| HTTP | `error` | When |
| --- | --- | --- |
| 400 | `invalid_request` | Missing body, or question shorter than 3 or longer than 500 characters |
| 502 | `upstream_unavailable` | Retrieval API or answer service unreachable |
| 504 | `upstream_timeout` | A downstream call passed its deadline |
| 500 | `internal_error` | Anything else |

The stub only produces `400`. The `502` and `504` shapes are reserved for the
real implementation.

## Run the stub

```bash
python -m pip install -r gateway/requirements.txt pytest
python -m uvicorn gateway.app:app --port 8000
```

Interactive docs are at `http://localhost:8000/docs`. Test hooks: a question
containing `[missing]` returns `insufficient_evidence`, and one containing
`[degraded]` returns `degraded`. Run the tests with
`python -m pytest -q tests/test_gateway.py`.

## Not decided yet

- **Orchestration.** This design has the gateway call the retrieval API and then
  the answer service. The alternative is for the answer service to call retrieval
  itself. It needs agreeing with Jordan and Kezhen.
- **Downstream contracts.** The retrieval and answer request and response shapes
  are not written yet.
- **Deadlines.** The overall timeout and the per-call timeouts.
- **Authentication, rate limiting and CORS.** None in the stub. The brief does not
  require them for a local demo.
- **Streaming.** Responses are returned whole; token streaming is out of scope.
- **Metrics set.** The stub exports only request count and duration. ADR-0005 also
  lists queue depth, retries, outbox backlog, source staleness and token cost,
  which belong to the other services' endpoints.
