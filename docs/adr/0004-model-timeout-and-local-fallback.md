# ADR-0004: Bounded model attempts and evidence-only fallback

- **Status:** Proposed (resilience implementation awaiting review)
- **Service:** Answer Service
- **Owner:** Jordan Hennessy
- **Updated:** 2026-11-16

## Context

Local Ollama generation can fail, stall or return invalid output. StudentPath
must bound waiting and preserve retrieved evidence. Unlimited retries or queued
generation can overwhelm student hardware and exceed Gateway's Answer deadline.

## Decision

Use one total generation deadline (default 20 seconds, below Gateway's 23-second
Answer deadline), including retries and backoff. Default to two attempts for
connection failures and HTTP 500/502/503/504, with 0.2-second initial exponential
backoff. Do not retry HTTP 429, read/write timeouts, invalid output or valid
refusals. A timed-out request may still be running in Ollama.

Use a per-process, fail-fast bulkhead (one admitted generation by default).
Excess requests fall back without queueing. Release admission after completion,
failure, cancellation or deadline. This is not a circuit breaker and does not
guarantee cancelled server-side GPU work stops; multiple workers multiply the
limit. Keep the local demo to one worker.

On generation failure or overload, return `degraded`, null answer and original
evidence/provenance with `fallback_used=true`. Empty evidence or an explicit
pending-update handover bypasses generation; the latter returns a fixed policy
explanation. Preserve request ID, model/prompt labels, index version and freshness.
Output is capped at 256 tokens; input is character-bounded, not exactly tokenized.

## Alternatives and consequences

Failing the request hides usable evidence. A second model adds resource use and
another dependency. Retrying all errors can duplicate expensive generation or
repeat malformed output. Bounded retries recover some transient failures; the
bulkhead protects client resources but sacrifices generated answers under load.
Evidence-only fallback retains sources while reducing usefulness. Citation
validation does not prove factual support. A circuit breaker remains an option
if measurements show repeated failures justify a cool-down period.

## Evidence and reconsideration

Twenty-one mocked failure/recovery and configuration tests pass, including
retry exhaustion, shared deadline, overload rejection and cancellation recovery.
Full branch suite: 340 passed, 6 optional cases skipped, one existing warning.
See `tests/test_answer_resilience.py`. The real local model also passed supported, unrelated-evidence, missing-model
and injected-503 recovery smoke checks; see
`docs/answer-resilience-checks-2026-11-16.md`. Repeated live evaluation, exported
metrics and usage accounting remain follow-up work. Revisit defaults using
repeated trials on team hardware; any retry must share the Gateway deadline.
