# Proposed pending-update handover to the Answer Service

Date: 2026-11-05. Owner: Jordan Hennessy.  
Status: proposal for Jordan and Emeka to review. No runtime or OpenAPI changes
are made by this document. The examples below are not accepted by current APIs.

Related proposal: [PR #19, ADR-0003](https://github.com/chukwuemekanwoke-jpg/comp41720-ai-design-critique/pull/19).

## What has been agreed, and what is proposed

Emeka confirmed that the Gateway should pass the decision to the Answer Service,
and the Answer Service should construct the response. Retrieval owns detecting
which relevant evidence is affected by a confirmed source update.

The field names, validation, response wording and model behaviour below are
proposals.

In plain language:

1. Retrieval reports: "This question uses a saved copy of a source that changed."
2. Gateway passes that decision and its source/version facts to Answer.
3. Answer constructs a clear explanation and returns it to Gateway.
4. Gateway forwards it; the frontend displays the explanation and official links.

## Proposed model behaviour

For this explicit pending-update decision, use a fixed message template and do
not call Ollama. This avoids turning known outdated evidence into advice, works
when Ollama is unavailable, and makes the explanation testable. This remains a
design choice for owner review; keeping the Answer Service in the path does not
require calling Ollama for every response.

Normal requests continue through existing evidence-only or Ollama paths. An
Ollama failure remains `degraded`; this policy refusal is `insufficient_evidence`
with an explicit reason. No new top-level status is proposed.

## Proposed request addition

Keep `POST /v1/answers`, `X-Request-ID` and existing request fields. Add optional
`abstention`. If absent or null, use the existing behaviour. If present, it is an
explicit instruction to construct a policy refusal, regardless of configured
generation mode. It must not be inferred by the model from passage text.

Example synthetic request, using `X-Request-ID: pending-update-example-1`:

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
  "last_success_at": "2026-11-04T09:00:00+00:00",
  "abstention": {
    "reason": "pending_source_update",
    "affected_sources": [
      {
        "source_id": "SYN001",
        "indexed_source_version": 1,
        "latest_source_version": 2,
        "detected_at": "2026-11-05T09:00:00+00:00"
      }
    ]
  }
}
```

The Gateway still supplies the pinned evidence, including affected passages,
because Answer must validate which source the decision refers to. Answer must
not feed those passages to generation on this refusal path.

| Proposed field | Meaning |
| --- | --- |
| `abstention` | Optional decision handed over by Gateway |
| `reason` | Initially only `pending_source_update` |
| `affected_sources` | Nonempty list of the relevant sources with a confirmed newer version |
| `source_id` | Identifier matching a source in the supplied evidence |
| `indexed_source_version` | Version of that source in the pinned evidence |
| `latest_source_version` | Newer version confirmed by Collector status |
| `detected_at` | Actual change-detection timestamp; null if unavailable from legacy history |

The Collector already calls its latest version `source_version`; the explicit
`latest_source_version` name here distinguishes it from the evidence's older
`source_version`. This is a mapping, not a Collector/event schema change.

## Proposed response addition

Keep the existing answer envelope. Add `abstention` only when this policy refusal
occurs; omit it from normal/generated, empty-evidence and degraded responses.
Do not put the explanation in `answer`: that would contradict the existing
no-claims rule for `insufficient_evidence`.

Return HTTP 200 for a valid policy refusal and echo `X-Request-ID` in both the
response header and body, as for other valid answer requests. A policy refusal
is distinct from a malformed request, which continues to return HTTP 400.

```json
{
  "request_id": "pending-update-example-1",
  "status": "insufficient_evidence",
  "answer": null,
  "checklist": [],
  "sources": [],
  "index_version": "synthetic-index-1",
  "last_success_at": "2026-11-04T09:00:00+00:00",
  "fallback_used": false,
  "model": {
    "name": "policy-response",
    "prompt_version": "none"
  },
  "notice": "Information only. This is not an eligibility decision or legal advice.",
  "abstention": {
    "reason": "pending_source_update",
    "message": "One or more sources used for this question have changed and the saved information has not been updated yet. Check the linked official sources or try again shortly.",
    "affected_sources": [
      {
        "source_id": "SYN001",
        "url": "https://example.org/synthetic-guidance",
        "indexed_source_version": 1,
        "latest_source_version": 2,
        "detected_at": "2026-11-05T09:00:00+00:00"
      }
    ]
  }
}
```

The generic explanation is fixed text; the UI displays source-specific URLs and
`detected_at` from `affected_sources` alongside it. The example URL is synthetic,
not an official immigration source. A null detection date displays "change date
unknown" rather than the current time. Source titles are not required because
the current evidence/status messages do not contain them.

`sources: []` means no passages are cited to support an immigration answer.
`abstention.affected_sources` explains why there is no answer and provides links
for checking the changed documents. Answer copies those URLs from request
evidence, not from model output. `policy-response` records that no model ran;
it is a new proposed metadata label, not a real model name.

## Proposed validation and safety rules

- Retain current input bounds and freshness requirements. Allow at most 10
  affected sources and require at least one, with strict types and no duplicate
  `source_id` entries. Reject unknown fields in the decision and source objects.
- Source IDs are nonblank strings of at most 256 characters. Both source
  versions are positive integers, not booleans or numeric strings. `detected_at`
  is a required key: its value is null or a timezone-aware timestamp string of
  at most 64 characters. Follow existing canonical URL validation on response links.
- Each affected source must occur in supplied evidence. Every passage for that
  source must agree on its indexed version and canonical URL.
- `indexed_source_version` must match the supplied source version, and
  `latest_source_version` must be strictly greater. These are per-source
  versions; neither is the collection's `index_version`.
- Accept a timezone-aware `detected_at` or explicit null, never manufacture it.
- A malformed decision returns HTTP 400, without calling Ollama or silently
  reverting to an ordinary answer. An unavailable check does not itself create
  a pending-update decision.
- Only the Gateway-to-Answer request gains this decision. The public question
  endpoint still accepts a question; users cannot submit this object through it.
  This describes the interface, not authentication of the internal network.
- Gateway verifies response reason, affected sources, versions, detection dates,
  URLs, request ID and pinned-index metadata against what it supplied. The full
  affected-source set must match, without omissions or duplicates. This response
  must remain `insufficient_evidence`, with null answer, empty checklist/sources
  and `fallback_used: false`; the model label must not claim a generation ran.
- Retrieval remains responsible for establishing a real pending update and
  preserving previously confirmed changes during status outages. Answer can
  validate the handed-over facts but cannot independently prove their freshness.

## Cross-service changes required after agreement

1. Emeka defines how Retrieval supplies the decision and Gateway forwards it.
2. Jordan adds the optional input, refusal construction and output to Answer.
3. Update shared/Answer/Gateway schemas and Gateway runtime validation together.
   Current models reject unknown fields; adding a response field only in Answer
   would cause Gateway to reject it. Keep legacy requests/responses working and
   update consumers before enabling producers to send the new fields.
4. Frontend displays the explanation, source links and known detection dates.
   Adding JSON fields alone does not make the explanation visible to users.
5. Cover the complete handover with producer/consumer integration tests.

No Collector, event or Indexer schema change is proposed. No status polling,
source-update detection or historical-index policy is implemented by Answer.
Use Emeka's ADR-0003 policy to decide when a historical request should receive
this decision; Answer obeys only an explicit handover.

## Acceptance checks to implement

- Valid pending-update handover returns the structured refusal in both Ollama
  and evidence-only modes, with zero calls to the model.
- Unknown sources, mismatched/non-newer versions, duplicates, invalid timestamps
  and unsupported reasons fail validation without generation.
- Multiple affected sources and null legacy detection dates are represented honestly.
- Existing normal generation, model refusals and model-failure fallback still work.
- Gateway accepts the agreed new response and rejects invented/mismatched details.
- Browser shows the actual explanation; affected questions refuse during the
  controlled delay, unaffected questions answer, and the refusal ends after
  updated evidence is published and the explicit decision is no longer sent.

## Decisions to confirm

- Jordan and Emeka: agree field names, fixed explanation, no-Ollama path,
  `insufficient_evidence` status and `policy-response` metadata.
- Emeka: confirm the Retrieval handover shape, warning path for unknown
  freshness, and frontend display. This proposal covers confirmed pending updates only.
- Agree a coordinated schema version/migration before treating the extension
  as an approved contract. Current schemas remain unchanged by this draft.
