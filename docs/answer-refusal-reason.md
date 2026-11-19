# Instruction-refusal reason handover

Agreed with Emeka on PR #29 on 18 November 2026.
Branch: `feature/answer-refusal-reason`, based on PR #29 commit `8acc303`.
This is a follow-up; it does not change PR #29 or implement a daily token ceiling.

## Answer response

Only an instruction-guard refusal includes:

```json
{
  "status": "insufficient_evidence",
  "answer": null,
  "checklist": [],
  "sources": [],
  "fallback_used": false,
  "model": {"name": "policy-response", "prompt_version": "instruction-guard-v2"},
  "refusal_reason": "instruction_override"
}
```

This is an excerpt: request ID, index version, freshness and the notice remain
present and unchanged. The response is HTTP 200 and makes no model call. It
cannot also include the pending-update abstention object. Response validation
rejects the reason with generated claims, evidence, fallback or another status.
Clients cannot supply this response field in their Answer request.

Answer omits the field entirely on generated answers, normal model refusals,
empty evidence, evidence-only fallback and pending-update explanations. An
internal null value is omitted by the serializer; required null answer and
freshness fields are preserved. The new field is optional and nonnull when sent
in the shared Answer schema, matching Emeka's #33 schema addition.

## Rollout order

1. Merge the existing Answer guard/evaluation PR #29.
2. Merge compatible Gateway support from #33 (which depends on #31).
3. Deploy the Answer producer change from this follow-up.

The old Gateway forbids unexpected fields and would return HTTP 502 for the
new labelled guard response. Consumer support therefore precedes emission.
The Gateway in #33 passes the reason through and exposes null on normal public
responses. No Gateway or frontend implementation is changed here. Frontend
wording for different refusal reasons and metric breakdowns are separate work.

## Verification, 18 November

- Nineteen new API/model cases cover label presence, omission on all other
  paths, malformed combinations, internal null serialization and request rejection.
- Full branch suite: 390 passed, 5 optional checks skipped, one existing warning.
- All six API specifications validate; whitespace checks pass.
- A temporary copy combining this Answer code with actual Gateway #33 code at
  `95fbc02` passed 108 targeted tests, including a real-app Gateway/Retrieval/
  Answer handover. Guard refusal passed through with zero model calls; the next
  normal request answered with the public reason null. HTTP model transport
  was mocked. No actual Ollama, Docker deployment or final-main check claimed.

The real-source guard scan remains blocked on the saved snapshots. The v2
pattern limitations remain unchanged by this label-only runtime change.
