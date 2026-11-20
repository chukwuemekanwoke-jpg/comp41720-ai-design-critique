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
eligibility-policy-v2. No new API fields or refusal_reason values are added.
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

## PR36 review follow-up: policy version 2

Emeka found that v1 refused how-to questions while missing everyday decision
phrasing. The if/whether rule now requires an explicit tell-me/say/decide/confirm
request. All four reviewed how/where/what questions reach generation in API
regressions. Direct personal requests still bypass generation and fallback.

Normalisation expands straight and curly apostrophe contractions. Output
checks now cover you're/you'll/you'd, will/would eligibility, qualification,
meeting requirements, likely approval, success and deportation claims. Both
answer and checklist are checked. Uncertainty and conditional guidance tests
remain passing. No questions, evidence or generated text are rewritten.

Current full suite: 451 passed, 5 optional skips, existing warning. All 59 known
flagged outputs remain detected. The paired v2 evidence JSON records the code
hash and verification scope; the v1 real-model smoke and frozen baseline remain
unchanged. No fresh live-model quality or final combined-stack claim is made.

Proposed handover: refusal_reason=personal_decision for these policy refusals,
omitted otherwise. This is not emitted yet. Coordinate Gateway/shared contract
support before enabling it, as with instruction_override. Without it these
responses retain the existing insufficient_evidence shape; policy version
metadata identifies the Answer-side mechanism.
