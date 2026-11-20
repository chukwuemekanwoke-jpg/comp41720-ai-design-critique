# Personal-decision policy follow-up, 20 November 2026

The frozen 880-request baseline contained 59 generated personal decisions or
false approvals: E01 20, E06 19, I02 20. All 200 eligibility/injection responses
were read, with per-response findings in evaluation/answer-safety-review-2026-11-20.json.
The source archive and all five supplied file hashes were verified. The
baseline is preserved unchanged, not rescored as a safe result.

## Behaviour

On a separate branch based on refusal-label PR34, a bounded English question
check detects direct personal eligibility/qualification and application-outcome
requests before generation or fallback. It examines only the question, not
official source text. A second check rejects generated personal qualification
or approval/refusal claims in either answer or checklist. It rejects the whole
output rather than rewriting a decision or exposing an evidence fallback.

Responses use existing insufficient_evidence, null answer, empty checklist and
sources, fallback_used false, model policy-response and prompt_version
eligibility-policy-v1. No new API fields or refusal_reason values are added.
Only instruction overrides use instruction_override. Request/index/freshness
metadata are retained. Pending-update explanations retain precedence, followed
by instruction-override detection, then the personal-decision policy.

The generic frontend refusal is unchanged: there is no new custom explanatory
message in this change. The generation prompt remains studentpath-answer-v1.

## Verification

- Full branch suite: 417 passed, 5 optional skips, existing Starlette warning.
- New tests cover personal-request bypass in both modes, answer/checklist
  rejection, uncertainty wording, ordinary guidance and pending-update precedence.
- All 59 saved flagged generated claims match the output policy check. This is
  development replay of known failures, not held-out evidence or a new 880 run.
- Local actual Ollama smoke: two personal questions and a SYSTEM impersonation
  returned no claims; a general fictional-form question generated blue. Saved
  responses: evaluation/answer-eligibility-live-2026-11-20.json.
- The initial restricted full-suite run could not open the Collector test's local
  socket; rerunning with local networking permitted passed.

## Limits and rollout

This is English pattern matching, not a complete intent/safety classifier.
Indirect wording, other languages, third-person decisions and unlisted phrasing
can escape it. Quoted personal decisions can be conservatively refused. Some
conditional guidance is permitted; a misleading condition can evade a simple
pattern check. General answers still need human support review.

No claim is made that merging the instruction guard alone fixes eligibility.
Keep baseline results unchanged and run the agreed cases on a separately pinned
final combined build. This branch depends on PR34; deploy Gateway PR33 before
emitting PR34's instruction_override field. It does not contain PR35's budget
or PR28's metrics. Only Answer implementation/tests and review docs changed.
