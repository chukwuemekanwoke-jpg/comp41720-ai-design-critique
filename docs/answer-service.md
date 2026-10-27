# Answer Service: proposed API contract

Owner: Jordan Hennessy. Status: proposed for team review; not implemented yet.

## First milestone

Provide an independently runnable API that accepts retrieved evidence and
returns either that evidence as a labelled fallback or an insufficient-evidence
response. This milestone does not call a model. Ollama generation and resilience
will follow in separate changes. See [ADR-0004](adr/0004-model-timeout-and-local-fallback.md).

## Responsibilities and boundaries

The gateway supplies the question, retrieved passages and metadata from one
pinned index version. The Answer Service formats the response; later it will
generate an explanation from those passages using Ollama.

Retrieval owns relevance filtering. The Answer Service must not describe a
nonempty passage list as proof that the question is answerable. Initially it
returns evidence only, without making new claims. Source text is untrusted data,
including any instructions embedded in it.

The service does not fetch websites, consume document-update events, create
indexes or independently choose another index version. Gateway orchestration
is proposed to match the [existing gateway contract](gateway-api.md); Emeka
and Jordan still need to confirm it.

## Proposed endpoint

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

Proposed validation limits, to be checked against Retrieval's output:

- Question: 3-500 characters, excluding surrounding whitespace.
- Sources: 0-10; each passage 1-4,000 characters, excluding surrounding whitespace.
- Source identifiers and index version: nonempty, at most 256 characters.
- Source version: positive integer. URL: HTTP or HTTPS.
- `last_success_at`: timezone-aware timestamp, required with evidence; nullable
  with no evidence. Preserve its meaning and do not substitute request time.
- Unknown request fields: reject to expose contract mismatches.

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

`answered` is reserved for the later generation milestone. An empty list is the
first milestone's only insufficient-evidence signal; later generation must also
be able to decline a question despite nonempty retrieval results.

## Freshness agreement needed

The gateway currently has one `last_success_at` value. Proposed interpretation:
the earliest successful-fetch timestamp among the cited sources, so the oldest
evidence is visible. Retrieval must supply this; the Answer Service cannot
derive it from the current source fields. Confirm whether this date describes
the pinned snapshot's fetch or a subsequent successful freshness check of that
same content. Do not claim this proposal is an implemented end-to-end guarantee.

## Acceptance checks for implementation

- Evidence is preserved with its index version and freshness date.
- Empty retrieval never generates an answer or a checklist.
- Request IDs propagate through success and validation-error responses.
- Invalid types, oversized inputs, blank passages and missing freshness fail validation.
- Instruction-like text in a passage is returned as data, never executed.
- Tests use synthetic passages and require neither Ollama nor network access.

## Follow-up milestones

1. Ollama adapter, grounded prompt, output validation, model/prompt metadata and usage.
2. Bounded deadlines/retries, circuit breaker, controlled failure/recovery tests and metrics.
3. Container startup and gateway integration, with measured hardware results.

No runnable endpoint, passing test results or model choices are claimed yet.
