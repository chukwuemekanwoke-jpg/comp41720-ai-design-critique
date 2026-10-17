# ADR-0005: Observability and answer-quality checks

- **Status:** Draft (proposed)
- **Service:** Gateway and evaluation (placeholder, to be confirmed)
- **Owner:** TBD
- **Date:** 2026-10-17

## Context

The brief asks for exported rate, error, latency and token usage or cost, and a
set of 30-40 questions with expected evidence, including missing evidence,
conflicting sources and injection attempts. StudentPath also has a specific risk:
a confident wrong answer about immigration guidance. We need metrics that show
the system is healthy and checks that show its answers are supported.

## Options considered

1. **Logs only.** Cheap, but hard to show rate, latency and cost at a glance.
2. **Metrics endpoint per service, scraped by a lightweight collector and
   dashboard.** Standard, runs locally in Docker Compose.
3. **Manual question testing only.** Does not give repeatable evidence.

## Decision (proposed)

Each service exposes a metrics endpoint (request rate, error rate, latency,
queue depth, retries, and for the answer service token usage and estimated
cost). The gateway adds a request id that is propagated across services so one
question can be traced end to end.

A scripted evaluation harness runs the 30-40 questions against the running
stack and checks, per question, that:

- the expected source passage is retrieved,
- a cited source supports each claim, or the system declines,
- missing-evidence questions get "I could not find this" and not a guess,
- instructions embedded in a retrieved document are not obeyed,
- the answer states the index version and last-checked date.

Results are written to a report that records the model, prompt and index
versions used.

## Consequences

- Health and cost are visible during the demo, including during injected
  failures.
- Quality claims are backed by a repeatable run, not by examples picked by hand.
- The question set must be written carefully and kept separate from any data
  used to tune prompts, to avoid grading on what we tuned against.
- Checks catch unsupported claims only where we wrote an expectation; they do
  not prove correctness in general.

## Open questions

- Whether support checking is rule-based, model-assisted, or both.
- Which dashboard tool runs reliably with one command offline.
