# Answer Service measurements

Branch: `feature/answer-metrics`, based on resilience commit `b3ae268`.
The resilience PR must be merged first, or this branch's PR should initially
use `feature/answer-resilience` as its base to show only measurement changes.

## View locally

From the repository root, install the existing development dependencies (the
runtime metrics dependency is also in `answer_service/requirements.txt`):

```sh
uv pip install -r requirements-dev.txt
ANSWER_GENERATION_MODE=ollama python -m uvicorn answer_service.app:app --host 127.0.0.1 --port 8003
```

In another terminal, send a request and view the counters:

```sh
curl -sS http://127.0.0.1:8003/v1/answers -H 'Content-Type: application/json' --data-binary @data/answer_request_demo.json
curl -sS http://127.0.0.1:8003/metrics
```

`GET /metrics` exports Prometheus text. It is an internal diagnostics route,
not a new Gateway/browser contract. Bind to loopback locally; a deployment
should keep metrics on its internal network. Scraping metrics and health checks
does not inflate answer request counts. No questions, evidence, URLs, model
names or request IDs are metric labels.

## Signals

| Metric | Meaning |
| --- | --- |
| `studentpath_answer_requests_total{status_class}` | POST /v1/answers count, including validation failures and server errors |
| `studentpath_answer_request_duration_seconds` | Histogram of elapsed HTTP handling time, including waiting/backoff; not client network latency |
| `studentpath_answer_responses_total{status}` | Constructed answered, degraded or insufficient_evidence outcomes; degraded responses are HTTP 200, not HTTP errors |
| `studentpath_answer_model_attempts_total{result}` | Completed/cancelled outgoing attempts, grouped by HTTP class, transport error or cancellation |
| `studentpath_answer_model_retries_total` | Retries scheduled; deadline expiry during backoff can prevent the next attempt |
| `studentpath_answer_model_active` | Currently admitted requests, including backoff |
| `studentpath_answer_model_rejected_total` | Generation requests rejected by the concurrency limit |
| `studentpath_answer_model_tokens_total{kind}` | Input prompt_eval_count and output eval_count reported by successful Ollama HTTP responses |
| `studentpath_answer_model_usage_missing_total{kind}` | Missing or invalid usage fields; counts are not fabricated |

Usage is recorded even if the HTTP-success response later fails output/citation
validation. Failed/cancelled HTTP requests may consume model resources without
reporting usage; totals are consequently incomplete billing/resource accounting.
Ollama prompt evaluation counts may reflect cache reuse rather than the complete
logical context length. These counters are not tokenizer-aware admission limits,
a daily budget or a monetary cost estimate. Local inference has no hosted API
charge, but hardware and electricity are not free.

Counters reset on process restart. Each app has its own registry. Use one worker
for the local demo; multi-process aggregation needs a separate deployment design.
A Prometheus scrape service, dashboard and system-wide metrics are not added here.
Coordinate those with the Gateway/evaluation owner rather than claiming this
endpoint completes the whole project's observability requirement.

## Dashboard queries for later integration

```promql
rate(studentpath_answer_requests_total[5m])
rate(studentpath_answer_requests_total{status_class="5xx"}[5m])
rate(studentpath_answer_responses_total{status="degraded"}[5m])
histogram_quantile(0.95, sum by (le) (rate(studentpath_answer_request_duration_seconds_bucket[5m])))
rate(studentpath_answer_model_tokens_total[5m])
```

Rate queries require a scraper and enough observations over time; a single
manual request does not produce a meaningful p95 or failure-rate benchmark.

## Verification

`python -m pytest -q tests/test_answer_metrics.py` covers request/error counts,
latency observations, registry isolation, retry/attempt accounting, reported and
missing usage, and pending-update bypass. Transport is mocked; these tests do
not establish model quality or measure real performance. Existing resilience
checks cover admission and cancellation behaviour.

On 16 November the full branch suite passed: 347 passed, 6 optional checks
skipped and one existing TestClient warning. A separate actual llama3.2:3b
request returned `answered` and exported reported input/output counts of
384/27, with active generation returning to zero. This single observation is
not a performance benchmark or proof of accurate total context accounting.
