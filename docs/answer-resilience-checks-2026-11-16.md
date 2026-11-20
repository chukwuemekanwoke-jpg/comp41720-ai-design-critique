# Answer resilience checks, 16 November 2026

Branch: `feature/answer-resilience`, based on main `6ab7007`, uncommitted
implementation at time of testing. Machine: Jordan's MacBook Pro M3, 16 GB RAM;
Python 3.14.8; locally installed Ollama `llama3.2:3b` tag ID `a80c4f17acd5`.
Model output and timings can vary; these are smoke checks, not a quality benchmark.

## Reproduce

With Ollama running and `llama3.2:3b` already installed:

```sh
OLLAMA_INTEGRATION=1 python -m pytest -q -s tests/test_ollama_integration.py
```

No model is downloaded by the tests. They use the synthetic blue-form fixture,
not live immigration pages. API requests run through FastAPI TestClient; model
requests use actual local HTTP except for the explicit injected failures below.

## Observed results

| Scenario | Observed behaviour |
| --- | --- |
| Supported synthetic evidence | `answered`, answer `a blue form`, original source retained, fallback false |
| Unrelated evidence | `insufficient_evidence`, null answer, no citations, fallback false |
| Deliberately missing model | `degraded`, original evidence retained, fallback true; no download |
| Two injected HTTP 503 responses, then recovery | First API request exhausted two attempts and returned `degraded`; next API request made a third transport call, reached real Ollama and returned `answered` |

The initial three live cases passed together. The added recovery case passed
separately. Initial single-run client times, including TestClient lifecycle:
4.024 seconds supported, 0.897 seconds unrelated, 0.015 seconds missing-model.
The supported case may include model loading. No p95, throughput or general
latency claim follows from these observations.

The recovery test injects 503 at the HTTP transport boundary, then forwards to
real Ollama. It does not stop/restart the Ollama process, induce an actual GPU
failure, or prove server-side cancellation.

## Automated failure coverage

`python -m pytest -q tests/test_answer_resilience.py`: 21 passed. Mocked cases
cover transient retries, exhausted retries and next-request recovery, terminal
errors, a deadline expiring during backoff, concurrency fallback and capacity
release after cancellation. Existing slow-generation and pending-update tests
remain in the suite.

Defaults: two total attempts; exponential backoff starts at 0.2 seconds; all
attempts/backoff share a 20-second deadline; one admitted generation per process.
Connection failures and HTTP 500/502/503/504 are retryable. Other HTTP errors,
read/write timeouts, invalid output and valid refusals are terminal.

The bulkhead bounds local client requests and rejects excess work without a
queue. It does not stop server-side work after cancellation and is not shared
between multiple worker processes. It is not a circuit breaker.

## Still to evaluate

- Repeated supported/unanswerable and injection-resistance cases.
- Exported latency/failure/usage measurements and resource budgeting.
- Whole deployed Gateway/Retrieval/Answer flow and live update demonstration.
- Team review of concurrency/fallback policy and configurable deadline alignment.
