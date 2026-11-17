# PR29 review follow-up, 17 November 2026

Reviewer: Emeka. Baseline PR head: `9cf5587`.

## False positives

The original first pattern matched verbs such as forget/disregard and then any
rules/evidence/instruction vocabulary within 80 characters. This classified
ordinary registration text and policy questions as model overrides. The
synthetic development evaluation did not expose that real-language failure.

`instruction-guard-v2` narrows this pattern to adjacent model-instruction
phrases: previous/prior/above/these/your instructions or prompts, all
instructions, and explicit system/developer/model/assistant instructions,
prompts or rules. Role-spoof and chat-delimiter checks remain unchanged.
Standalone evidence and ordinary rules are no longer targets. This intentionally
reduces coverage of bare commands such as disregard the evidence; it should not
be reported as preserving all v1 containment results. Indirect, multilingual,
encoded and quoted-text limitations remain. No new evaluation results replace
or invalidate the preserved historical v1 raw reports.

All five realistic sentences/questions supplied by Emeka now pass the guard.
A mocked API regression verifies that the registration evidence reaches the
model and is retained in the answered response. Existing explicit model-
instruction and role-spoof tests remain passing. These five examples are
regression fixtures, not evidence of zero false positives on the real corpus.

## Real-source scan still required

The local repo has a ten-source manifest, an initial question mapping and
synthetic demo pages. The shared Collector folder inspected on 17 November
contains early manifest/validation/milestone files; the collected ten-source
snapshot text was not located. Request its saved location from the team.
Do not substitute fresh website downloads or paraphrased expected answers and
call those the collected corpus. Scan all supplied passages and record source
versions/hashes, total passages, matches and any missing sources before claiming
this review point complete.

## Distinct refusal reason: proposed handover

Propose an optional Answer response field `refusal_reason`, with value
`instruction_override` on guard refusals and omitted otherwise. Keep pending
updates under their existing abstention object. This gives Gateway, frontend
and evaluators a machine-readable distinction without mislabelling an attack
as a source update. Preserve current null answer/empty claims/fallback false.

This field is not implemented or sent yet: current Gateway models forbid
unknown response fields, so emitting it now would turn these requests into
502 responses until the consumer is updated. Coordinate the exact field and
rollout with Emeka, who offered to add the Gateway side. The alternative of
extending abstention reasons also requires coordinated schema validation.

No Gateway/frontend/Collector/Indexer implementation changes in this follow-up.
