# ADR-0004: Model timeout and local fallback

- **Status:** Draft (proposed)
- **Service:** Answer service
- **Owner:** Jordan Hennessy
- **Date:** 2026-10-17

## Context

The answer service sends retrieved passages to a language model and returns an
explanation with sources. The model call is the slowest and least reliable step.
The brief requires one-command startup, local or free infrastructure, offline
fallbacks for dependencies, capped generation, and recovery from injected model
timeouts with retry limits.

## Options considered

1. **Single hosted model, fail on error.** Simple, but a timeout or missing key
   breaks the demo.
2. **Retry indefinitely.** Hides failure and can pile up requests.
3. **Bounded retries, then a local or simulated fallback.** Degrades
   predictably and keeps the demo runnable offline.

## Decision (proposed)

Call the primary model with a hard timeout and a small, fixed number of retries
with backoff. If it still fails, switch to a local or simulated model behind the
same interface. A circuit breaker stops calling the primary for a cool-down
period after repeated failures. Generation length is capped per request.

The fallback must still ground the answer. It returns the best-matching passages
with their source links and the version and `last_success_at` date, labelled as a
reduced answer (retrieved evidence without generated explanation). If there is
no sufficient evidence, the service says so and does not guess.

Prompt and model identifiers are recorded with every response so the version
metadata in the brief is complete.

## Consequences

- A model timeout produces a visible, labelled degraded answer, not an error.
- The demo can inject a timeout and show retries, the breaker opening, and the
  fallback taking over.
- The simulated model is not the real quality bar, so evaluation results must
  state which model produced them.
- Token usage and cost are capped and exported as metrics.

## Open questions

- Timeout, retry count and cool-down values.
- Which local model, if any, is practical on student hardware.
