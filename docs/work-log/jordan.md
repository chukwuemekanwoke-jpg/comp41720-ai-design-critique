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
