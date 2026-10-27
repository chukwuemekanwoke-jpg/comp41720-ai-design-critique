# Answer Service: proposed API contract

Owner: Jordan Hennessy. Status: evidence-only API and opt-in Ollama generation
implemented locally; integration contract proposed for team review.

## Implemented milestones

Provide an independently runnable API that accepts retrieved evidence and
returns either that evidence as a labelled fallback or an insufficient-evidence
response. This remains the default mode. Opt-in Ollama generation now adds a
validated answer or model refusal, with evidence-only fallback on errors.
Retries, circuit breaker and metrics are not implemented yet.
See [ADR-0004](adr/0004-model-timeout-and-local-fallback.md).

## Responsibilities and boundaries

The gateway supplies the question, retrieved passages and metadata from one
pinned index version. The Answer Service formats the response and optionally
generates an explanation from those passages using Ollama.

Retrieval owns relevance filtering. The Answer Service must not describe a
nonempty passage list as proof that the question is answerable. Initially it
returns evidence only, without making new claims. Source text is untrusted data,
including any instructions embedded in it.

The service does not fetch websites, consume document-update events, create
indexes or independently choose another index version. Gateway orchestration
is proposed to match the [existing gateway contract](gateway-api.md); Emeka
and Jordan still need to confirm it.

## Run and try the API

From the repository root:

```bash
uv venv --python 3.14
uv pip install --python .venv/bin/python -r answer_service/requirements-dev.txt
.venv/bin/python -m uvicorn answer_service.app:app --host 127.0.0.1 --port 8002 --reload
```

Create the environment only if it does not already exist. On Windows, the
environment interpreter is `.venv/Scripts/python.exe` instead. These are local
development instructions, not a container startup command.

Open `http://127.0.0.1:8002/docs`, expand `POST /v1/answers`, select **Try it out**,
paste the example request below, and select **Execute**. A `200` response with
`status: degraded` is expected: generation is deliberately not enabled yet.
`GET /healthz` checks only whether the application is responding.

Alternatively, while the server is running, use another terminal:

```bash
curl -sS http://127.0.0.1:8002/v1/answers \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: manual-demo-1' \
  --data-binary @data/answer_request_demo.json
```

For the empty-evidence case, submit:

```json
{
  "question": "What does the fictional application require?",
  "sources": [],
  "index_version": "synthetic-index-1",
  "last_success_at": null
}
```

Expect `insufficient_evidence`, `answer: null` and `fallback_used: false`.
Neither response claims to have evaluated a real immigration question.

## Enable Ollama generation

Start the Ollama application and ensure the chosen model is installed:

```bash
ollama list
# Only if not installed; this downloads model weights and requires internet:
ollama pull llama3.2:3b
```

Stop any existing Answer Service with Control+C. From the repository root:

```bash
ANSWER_GENERATION_MODE=ollama \
OLLAMA_MODEL=llama3.2:3b \
.venv/bin/python -m uvicorn answer_service.app:app --host 127.0.0.1 --port 8002 --reload
```

Use the same request fixture through `/docs` or curl. In generation mode, expect
an `answered` response when the model finds support. For unrelated evidence the
model can return `insufficient_evidence`, even with nonempty input passages.
If the model is missing, unavailable, too slow or produces invalid output, the
service returns the existing evidence-only `degraded` response.

The service never downloads a model automatically. Set generation mode to
`evidence_only` (or omit it) to run without Ollama. Configuration is read at
process startup; restart after changes. `.env` files are not loaded automatically.
PowerShell users should set these process variables with `$env:NAME='value'`
before invoking the Python command.

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `ANSWER_GENERATION_MODE` | `evidence_only` | `evidence_only` or `ollama` |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama HTTP(S) origin, without credentials/path |
| `OLLAMA_MODEL` | `llama3.2:3b` | Configurable model tag; provisional selection |
| `OLLAMA_TIMEOUT_SECONDS` | `20` | Total client-side deadline for one model call |
| `OLLAMA_TEMPERATURE` | `0` | Generation temperature |
| `OLLAMA_MAX_OUTPUT_TOKENS` | `256` | Generation token cap, including JSON structure |
| `OLLAMA_CONTEXT_TOKENS` | `8192` | Requested model context size |
| `ANSWER_MAX_INPUT_CHARACTERS` | `8000` | Cap on serialized question/evidence before model submission |

These are experimental defaults, not team-approved performance guarantees.
Oversized generation inputs fall back without truncating the returned evidence.
The character cap is not an exact token budget: multilingual or unusual text can
tokenize differently. Context truncation by the model runtime is not fully
detected here; tokenizer-aware budgeting remains follow-up work.
The deadline bounds the caller's wait, not a guarantee that server-side GPU work
stops immediately. This milestone makes one attempt only.

Inside Docker, loopback refers to that container, not the host Mac. A future
Compose deployment must explicitly configure the Ollama address. No container
configuration is added in this milestone.

## Generation and validation

`config.py` reads configuration, `ollama.py` calls the model, `service.py` chooses
the response, and `app.py` exposes the HTTP API. One async HTTP client is created
at application startup and closed on shutdown.

The adapter uses [Ollama's chat API](https://docs.ollama.com/api/chat) with
`stream: false` and a [structured-output schema](https://docs.ollama.com/capabilities/structured-outputs).
Prompt version `studentpath-answer-v1` is stored with the prompt in `ollama.py`.
This differs from the earlier free-text experiment and was tested separately.

The model returns an answer, checklist and one-based passage indices, or a
structured refusal. Python checks the schema, response completion and citation
indices. It rejects unknown fields, missing/invalid citations, truncated outputs
and refusals containing claims. Python attaches URLs, dates and version metadata
from the request; it never asks the model to supply them.

`answered` responses include only the selected input passages. A model refusal
returns no cited sources. Both retain the supplied index version and timestamp;
the timestamp remains a conservative oldest-input date if only a subset is cited.
Fallback responses preserve all supplied evidence and report model `evidence-only`
and prompt `none`, identifying the response producer. Model refusals are normal
outputs and are not automatically retried as transport errors.

Valid citation indices do not establish that the generated claims are supported.
The prompt asks for grounding and resistance to embedded instructions; this is
not a proven prompt-injection defence or semantic fact checker.

## Endpoint

`POST /v1/answers`

The gateway passes its `X-Request-ID` header through. Follow the gateway's
existing rule: preserve 1-64 letters, digits, underscores or hyphens; otherwise
generate an ID. Return the same ID in the response header and body.

Example input uses synthetic evidence, not real immigration guidance:

```json
{
  "question": "What does the fictional application require?",
  "sources": [
    {
      "source_id": "SYN001",
      "snapshot_id": "SYN001:fixture-v1",
      "source_version": 1,
      "url": "https://example.org/synthetic-guidance",
      "passage": "Synthetic test only: the fictional application requires a blue form."
    }
  ],
  "index_version": "synthetic-index-1",
  "last_success_at": "2026-10-27T09:00:00+00:00"
}
```

`snapshot_id` is opaque to this service; the example is not a Collector event
and must not be used to test its SHA-256 contract.

Implemented validation limits, still to be agreed with Retrieval:

- Question: 3-500 characters, excluding surrounding whitespace.
- Sources: 0-10; each passage 1-4,000 characters in total, with non-whitespace
  content. Passage text is preserved without trimming or normalization.
- Source identifiers and index version: nonempty, at most 256 characters.
- Source version: positive integer. URL: HTTP or HTTPS.
- `last_success_at`: timezone-aware timestamp, required with evidence; nullable
  with no evidence. Preserve its meaning and do not substitute request time.
- Unknown request fields: reject to expose contract mismatches.
- Types are strict: for example, `source_version: "1"` is rejected rather than
  silently converted to an integer. URLs are limited to 2,048 characters and
  timestamps to 64.

The passage limit bounds input size, not tokens. Actual model context budgeting
must be addressed when Ollama is introduced.

## First-milestone response

```json
{
  "request_id": "example-request-1",
  "status": "degraded",
  "answer": null,
  "checklist": [],
  "sources": [
    {
      "source_id": "SYN001",
      "snapshot_id": "SYN001:fixture-v1",
      "source_version": 1,
      "url": "https://example.org/synthetic-guidance",
      "passage": "Synthetic test only: the fictional application requires a blue form."
    }
  ],
  "index_version": "synthetic-index-1",
  "last_success_at": "2026-10-27T09:00:00+00:00",
  "fallback_used": true,
  "model": {
    "name": "evidence-only",
    "prompt_version": "none"
  },
  "notice": "Information only. This is not an eligibility decision or legal advice."
}
```

This matches the gateway's documented public fields without its placeholder
`stub` field. No generation model or prompt has run in this response.

| Condition | HTTP | Status | Behaviour |
| --- | --- | --- | --- |
| Evidence supplied, generation not configured | 200 | `degraded` | Preserve evidence/metadata; null answer; empty checklist; fallback true |
| No evidence supplied | 200 | `insufficient_evidence` | Null answer; empty sources/checklist; fallback false |
| Invalid request | 400 | Error response | `request_id`, `error: invalid_request`, helpful `message` |

In default evidence-only mode, an empty list is the only insufficient-evidence
signal. In Ollama mode, the model can also decline despite nonempty passages;
this returns null answer, empty checklist/sources and `fallback_used: false`.
An `answered` response contains generated text, cited input passages and
`fallback_used: false`.

Validation errors use the gateway's `request_id`, `error`, `message` shape.
The message identifies invalid field locations without echoing request contents.
For example:

```json
{
  "request_id": "example-request-1",
  "error": "invalid_request",
  "message": "Invalid answer request. Check: body.question."
}
```

## Freshness agreement needed

The gateway currently has one `last_success_at` value. Proposed interpretation:
the earliest successful-fetch timestamp among the cited sources, so the oldest
evidence is visible. Retrieval must supply this; the Answer Service cannot
derive it from the current source fields. Confirm whether this date describes
the pinned snapshot's fetch or a subsequent successful freshness check of that
same content. Do not claim this proposal is an implemented end-to-end guarantee.

The inspected Indexer database does not retain source URLs or Collector fetch
timestamps in its passage/manifest tables. Agree how Retrieval obtains those
fields before integration. Also agree whether to add the Indexer's existing
`passage_id` for precise citation tracing; the current API follows the gateway's
existing source shape and rejects this extra field until the contract changes.

## Acceptance checks for implementation

- Evidence is preserved with its index version and freshness date.
- Empty retrieval never generates an answer or a checklist.
- Request IDs propagate through success and validation-error responses.
- Invalid types, oversized inputs, blank passages and missing freshness fail validation.
- Instruction-like text in a passage is returned as data, never executed.
- Tests use synthetic passages and require neither Ollama nor network access.

## Follow-up milestones

1. Broader model evaluation, semantic support checks and tokenizer-aware input budgeting.
2. Bounded retries, circuit breaker, controlled failure/recovery tests and metrics/usage.
3. Container startup and gateway integration, with measured hardware results.

## Verification and current limits

```bash
.venv/bin/python -m pytest -q tests/test_answer_service.py
.venv/bin/python -m pytest -q
```

On 2026-10-27, Python 3.14.8: **35 Answer Service cases passed**; the full
repository suite reported **62 passed, 1 skipped**. The skip is the opt-in live
RabbitMQ test. The existing Starlette/httpx TestClient deprecation warning
remains. API tests execute the real FastAPI application in-process, without a
network listener, Ollama, a broker or the gateway.

For the Ollama adapter milestone, the full default suite reported **95 passed,
4 skipped**: three opt-in Ollama checks and the live RabbitMQ check are skipped.
The existing TestClient warning remains. The simulated adapter tests cover
timeouts, connection/HTTP errors, malformed/truncated outputs, invalid citations,
input budgets, configuration and normal model refusal. They make no real model calls.

Explicit live checks:

```bash
OLLAMA_INTEGRATION=1 .venv/bin/python -m pytest -q -s tests/test_ollama_integration.py
```

On 2026-10-27 all **3 live checks passed** using actual HTTP to local
`llama3.2:3b` through the API's in-process TestClient. Supported synthetic evidence
returned `answered` (`a blue form`, empty checklist) in 3.168 seconds; unrelated
evidence returned `insufficient_evidence` in 0.937 seconds; an intentionally
nonexistent model returned evidence-only `degraded` in 0.029 seconds. These are
single-run client elapsed times including TestClient startup/shutdown, not a
latency benchmark. The nonexistent-model request downloads nothing.

No general answer quality, model injection defence, live gateway integration,
container startup, retries, circuit breaker or metrics are demonstrated yet.
The service trusts the caller's provenance: it validates metadata shape, not
that every supplied source actually belongs to the stated index version.
The input bounds do not implement transport-level request-size limits or rate limiting.
