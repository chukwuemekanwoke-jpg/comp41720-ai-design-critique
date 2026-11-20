# Jordan Hennessy: work log

## 2026-10-27 - API milestone preparation

### Current state

- Working branch: `feature/answer-service-api`.
- Ownership: Answer Service and ADR-0004, confirmed in team discussion on 20 October.
- Development hardware reported by Jordan: MacBook Pro M3, 16 GB RAM.
- Existing gateway response vocabulary and ADR-0004 reviewed with AI assistance.
- Proposed service contract documented in `docs/answer-service.md`.

### Verification and limits

- Branch and clean initial working tree checked before adding documentation.
- This change adds documentation only. No endpoint has been implemented or tested.
- No real model performance, timeout recovery or gateway integration verified.
- Proposed limits, orchestration and freshness semantics await owner/team review.

### Next actions

1. Jordan reviews the proposed request/response contract.
2. Implement the API and evidence-only fallback, with synthetic-input tests.
3. Share the contract in a draft PR for Emeka's review before integration.
4. Measure Ollama behaviour before choosing model and resilience settings.

## 2026-10-27 - Evidence-only API implementation

### Completed

- Local Python 3.14.8 environment and initial health-check app set up by Jordan.
- Baseline suite verified: 27 passed, 1 skipped.
- With AI assistance, added strict request/response models and `POST /v1/answers`.
- Evidence returns `degraded` with no generated answer; empty retrieval returns
  `insufficient_evidence`. Source text, index version and timestamp are preserved.
- Added gateway-compatible request IDs and HTTP 400 validation errors.
- Added a synthetic request fixture, API tests and manual run instructions.
- Declared Pydantic directly because the service now imports it directly.

### Verification

- `.venv/bin/python -m pytest -q tests/test_answer_service.py`: 35 passed.
- `.venv/bin/python -m pytest -q`: 62 passed, 1 skipped, 1 warning.
- `git diff --check`: passed before final documentation update.
- Tests cover evidence/metadata preservation, empty retrieval, malformed input,
  bounds/types, request IDs, health and API schema. Tests run in-process.
- Live RabbitMQ test skipped without explicit broker configuration. Existing
  Starlette/httpx deprecation warning persists.
- No manual live HTTP request, gateway integration, Ollama, failure recovery or
  container test performed for this milestone yet.

### Review and next actions

- Jordan to inspect the code and try both response cases through `/docs`.
- Proposed contract still needs Emeka's review. Source URL/freshness delivery
  and optional passage IDs remain integration questions.
- Run instructions are in `docs/answer-service.md`. Review changes before committing.
- Next service milestone: Ollama integration and grounded output validation.

## 2026-10-27 - Manual Ollama checks

- Jordan reported manually trying the evidence-only API and committed the milestone.
- Jordan then sent standalone curl requests directly to local Ollama; the Python
  service is not connected to Ollama yet.
- `llama3.2:1b` incorrectly refused the answer-present example with both tested prompts.
- `llama3.2:3b` answered the same example correctly under the revised prompt and
  correctly declined when given unrelated evidence.
- Recorded exact prompts, outputs, model tags, usage and reported timings in
  [the initial model checks](../model-checks-2026-10-27.md).
- 3B results: 2.312 seconds including 1.860 seconds loading; subsequent request
  0.215 seconds, with 80 cached input tokens. These are Ollama-reported durations,
  not an independently measured latency benchmark.
- Results come from Jordan's shared JSON responses, not independent reruns.
- Next: implement a configurable Ollama adapter and test structured responses;
  keep model choice provisional pending broader evaluation.

## 2026-10-27 - Ollama adapter milestone

### Completed

- Added opt-in Ollama mode with configurable URL/model, temperature, context,
  generation cap, input-character budget and a total client-side deadline.
- Added structured-output prompt `studentpath-answer-v1` and validation of
  completed model responses/citation indices. Python supplies citation metadata.
- Model refusal returns `insufficient_evidence`; failed/invalid model calls
  preserve the evidence-only fallback. Default mode still requires no Ollama.
- Added reusable async client lifecycle, adapter tests and opt-in live tests.
- Inspected roadmap video: Emeka added it on 24 October; FFmpeg encoder metadata
  and a sampled frame indicate an animated roadmap page, but no authoring
  platform was identified. Encoding software is not proof of the creation tool.

### Verification

- Default full suite: 95 passed, 4 skipped, 1 existing TestClient warning.
- `OLLAMA_INTEGRATION=1 .venv/bin/python -m pytest -q -s tests/test_ollama_integration.py`:
  3 passed against actual local Ollama via the Answer Service in-process API.
- Supported evidence: `answered`, `a blue form`, 3.168 seconds.
- Unrelated evidence: `insufficient_evidence`, 0.937 seconds.
- Deliberately nonexistent model: `degraded`, original evidence preserved, 0.029 seconds.
- These single-run times include TestClient lifecycle; no general latency claim.
- Mocked transport/deadline tests are separate from real HTTP checks.

### Limits and next actions

- No retries, circuit breaker, metrics, container or gateway integration yet.
- Prompt constraints and valid citation indices do not prove semantic support
  or injection resistance. Character limits are not exact token budgeting.
- Experimental defaults and ADR-0004 remain proposed for Jordan/team review.
- Jordan to try Ollama mode through the browser and review the adapter code
  before committing. Changes remain on the existing feature branch.

## 2026-11-05 - Pending-update handover proposal

- Updated local main to `cde9109`; current Python baseline: 278 passed,
  4 optional integration tests skipped, 1 existing TestClient warning.
- Reviewed the supplied group chat, submitted proposal, lecturer feedback and
  PR #19's proposed stale-source refusal policy. No GitHub review/approval was
  submitted by the assistant.
- Emeka's response supplied by Jordan confirms Gateway should pass the decision
  to Answer so Answer constructs the response. It does not specify model usage
  or the wire fields.
- Working branch created by Jordan: `feature/answer-abstention`.
- Drafted [the handover proposal](../answer-abstention-handoff.md): optional
  explicit decision, affected source versions/detection dates, structured refusal
  and coordinated Gateway/schema/frontend changes.
- Fixed-template/no-Ollama behaviour and field names are proposals awaiting
  owner review; no runtime or OpenAPI implementation changed in this step.
- Next: Jordan reads the request/response examples and agrees the proposal with
  Emeka before implementing the shared handover.

### Pre-PR proposal review

- Checked the proposal against existing Answer/Gateway runtime models, the
  shared OpenAPI response and Collector status fields.
- Clarified HTTP 200 refusal versus HTTP 400 invalid input and request-ID echo.
- Tightened proposed bounds, required nullable detection dates and exact
  affected-source matching; made the fixed wording cover multiple sources.
- Kept the fixed-template/no-Ollama path explicitly proposed. Emeka's clarified
  requirement is that Answer stays in the response path, not that every response
  must be generated by a model.
- Runtime behaviour, formal schemas and other owners' code remain unchanged.
- Verification: both JSON examples parsed; their existing fields validate
  against current Answer/Gateway models; only the proposed `abstention` field
  is rejected by current models, as documented. Example reason, versions, URLs,
  timestamps and refusal semantics match across the handover. `git diff --check`
  passed. No full suite rerun for these documentation-only clarifications.

## 2026-11-05 - Provisional Answer-side abstention implementation

- Added optional `abstention` input, strict pending-source types and validation
  against supplied source IDs, versions and canonical URLs.
- Added a response path before model generation. It returns the fixed proposed
  explanation, affected-source URLs and original detection dates. Unknown dates
  remain null. It makes no model call in either configured generation mode.
- Malformed handovers return HTTP 400. Normal requests retain existing behaviour
  and omit the new response field, including preservation of required null fields.
- Added `data/answer_abstention_demo.json` and 40 API/validation cases.
- New abstention suite: 40 passed. Full suite: 318 passed, 4 optional integration
  cases skipped, 1 existing TestClient warning. `git diff --check` passed before
  documentation updates.
- Automated tests use in-process API calls and mocked model transport.
- Jordan supplied a manual API response matching the pending-update example:
  `insufficient_evidence`, null answer, `policy-response` metadata, the expected
  explanation and original source/version/detection details. This checks the
  direct endpoint; it is not a Gateway/frontend or live-model demonstration.
- Gateway, Retrieval, frontend and shared OpenAPI schemas remain unchanged.
  The pending-update response requires coordinated consumer/schema changes.
- Field names, fixed-message policy and metadata remain provisional until review.
  Local changes are not committed or pushed to PR #20 at this checkpoint.

## 2026-11-16 - Answer contract alignment

- Branch: `feature/answer-contract-alignment`, based on current main `6ab7007`.
- Updated Answer OpenAPI to 0.3.0 and shared schemas to 1.2.0 to describe
  the pending-update handover already implemented in PR #20.
- Documented required nullable detection dates, source/version matching,
  fixed policy-response metadata, HTTP 400 invalid decisions and HTTP 200
  refusals without model generation. Normal Answer responses omit abstention.
- Updated the contract inventory and mapping notes. Retrieval cache policy,
  Gateway forwarding and frontend changes remain separate work.
- Validation: all six OpenAPI documents passed; 40 existing abstention tests
  passed with the existing TestClient warning; diff whitespace check passed.
- Also validated pending, normal and explicit-null requests and actual API
  responses against the OpenAPI schemas. Missing detected_at was rejected by
  both the schema and the API. Contract dependencies installed from the existing
  requirements-contracts.txt; dependency files and runtime code unchanged.

## 2026-11-16 - Repeatable Answer development evaluation

- Independent branch `feature/answer-evaluation`, based on main `04e5a41`.
- Added 12 synthetic development cases, a local-model evaluation harness and
  16 scorer/fixture tests. No runtime or prompt changes. These are not held-out
  questions, official immigration facts or full-pipeline evaluation.
- Harness preserves responses, per-trial checks, timings, model/runtime metadata,
  dataset/prompt/source/harness hashes, commit and dirty-tree state.
- Full automated suite: 345 passed, 5 optional checks skipped, existing warning.
  This main-based branch does not include the separate resilience/metrics PRs.
- Full baseline: 20 trials per case, 240 requests, 180 expected outcomes passed.
  E08 and E10 followed planted instructions; E09 consistently returned evidence
  fallback. Keep safety failure and reduced usefulness distinct.
- Corrected a checker that initially mislabelled degraded evidence fallback as
  refusal claims; the interrupted run is retained and excluded from totals.
- Raw results and interpretation under docs/evaluation. Baseline command exits
  nonzero because expectations failed; the report is complete and preserved.
- Next: runtime injection mitigation and unseen attack variants; broader source
  evidence and connected-system evaluation remain separate work.


## 2026-11-16 - Explicit override refusal after baseline

- Continued on `feature/answer-evaluation` after baseline commit `97700ad`.
- Added instruction-guard-v1 for explicit override/role markers in questions
  and passages, including representative Unicode and whitespace variants.
- Refuses the full request before model generation or suspect evidence fallback
  in either mode. Pending-update explanations retain priority. No public fields
  added; policy label distinguishes this from generated output.
- Original evidence text remains intact in input models. Updated one earlier
  fallback-content test because returning detected attack text is intentionally
  replaced by refusal. Twenty new guard checks pass.
- Full suite: 365 passed, 5 skipped, existing warning. No resilience/metrics PR
  code is included on this main-based branch.
- Preserved baseline and expectations. Follow-up 240 requests: 200 original
  expectations passed. E08/E09 still fail usefulness expectations, but all 60
  original attack requests now return policy refusals instead of model answers.
- Additional 25-request development run: role/Unicode variants refused by guard,
  benign instructions answered; indirect evaluator pressure missed by guard but
  refused by the model in five trials. Not held-out security evidence.
- The short variants run overlapped part of the main repeat run. Results retain
  this operator note; no comparative timing or throughput claims are made.
- Added method, limits and result summaries. Team review required for refusal
  policy; specific frontend explanations remain coordinated contract work.
- Runtime changes and follow-up evidence remain uncommitted for Jordan's review.

## 2026-11-17 - PR29 false-positive review

- Read Emeka's changes-requested review. Confirmed the original guard was too
  broad: ordinary forget/disregard sentences matched later rules/evidence nouns.
- Narrowed model-instruction targets, versioned as instruction-guard-v2, and
  added five realistic regression cases plus an answered API evidence case.
- Focused guard/service tests: 61 passed, existing warning. Historical v1
  baselines remain unchanged; narrowing coverage requires follow-up evaluation.
- Real collected corpus not located in repo or shared Collector folder. Asked
  Jordan for its location; no corpus-wide zero-false-positive claim made.
- Prepared proposed refusal_reason=instruction_override handover notes. Not
  emitted until Gateway compatibility is coordinated; no teammate code changed.
- Runtime changes remain uncommitted. Review items 2 (corpus scan) and 3
  (distinct reason) remain outstanding; PR is not ready to re-request approval.

## 2026-11-16 - Bounded model retries and concurrency

- Separate branch: `feature/answer-resilience`, based on main `6ab7007`.
- Added at most two attempts by default for connection failures and transient
  server errors, with exponential backoff inside the existing total deadline.
- No retry for overload HTTP 429, other client errors, read/write timeouts,
  invalid model output or valid refusals.
- Added a fail-fast per-process bulkhead, default capacity one. Busy requests
  preserve evidence via the existing degraded response; no generation queue.
- Tests exercise recovery, exhausted retries, terminal errors, deadline during
  backoff, concurrency rejection and capacity release after cancellation.
- New tests: 21 passed. Full suite: 340 passed, 5 optional cases skipped,
  existing TestClient warning. The Collector demo requires local socket access;
  rerunning with that access passed after the initial permission-limited run.
- Updated service settings/run notes and ADR-0004 for review. Existing Drive ADR
  still describes merged behaviour; update it after agreement on this change.
- No public API schema, dependency or Gateway changes. No live Ollama throughput
  or recovery measurements claimed. Work remains uncommitted for review.

### Live-model verification

- Installed local `llama3.2:3b` answered the supported synthetic fixture and
  refused unrelated evidence; a deliberately missing tag returned evidence-only
  fallback. All three opt-in cases passed.
- Added and passed an opt-in recovery case: inject two HTTP 503 failures, verify
  fallback after the configured attempts, then forward the next request to real
  Ollama and verify an answer. This does not stop/restart the model process.
- Recorded exact scope, commands, single-run observations and limitations in
  `docs/answer-resilience-checks-2026-11-16.md`. Mocked concurrency and cancellation
  tests remain separate from live-model evidence. No quality benchmark claimed.

- Final default suite after adding the opt-in recovery test: 340 passed,
  6 skipped (four model checks and two broker checks), one existing warning.
