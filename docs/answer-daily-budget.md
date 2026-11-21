# Persistent daily model allowance

Branch: `feature/answer-daily-budget`, based on the metrics/resilience work in
PR #28 (`f042fe4`). This is separate from the guard and refusal-label PRs.
Merge the parent work first; use its branch as the PR base while it is open.

## Policy and rationale

The service enforces a configurable ceiling on **conservative admission
charges**, not exact reported token usage. Before each HTTP model attempt it
charges `OLLAMA_CONTEXT_TOKENS + OLLAMA_MAX_OUTPUT_TOKENS`. With current defaults
that is 8192 + 256 = 8448 units per attempt. The daily default of 1,000,000 admits
at most 118 such attempts; leftover allowance below 8448 cannot start another.
A retry is another attempt and needs another full charge.

This intentionally overcounts short/cached calls. Failed HTTP calls, invalid
output, missing usage fields and cancellation do not refund charges. Charging
before HTTP avoids admitting unaccounted work after a crash or missing report.
It also avoids depending on model-generated or missing usage values. The
separate Prometheus token counters retain Ollama's reported usage.

If quota cannot admit an attempt, return the existing HTTP 200 evidence-only
`degraded` response with original sources, null answer and fallback_used=true.
There is no public response schema change. A retry denied after the first failed
attempt also falls back. If the ledger is corrupt, unwritable or locked beyond
its bounded wait, generation is denied and evidence remains available.

## Persistence and concurrent requests

SQLite stores one charged total per UTC date. An immediate transaction checks
and increments atomically, even across instances/processes sharing that file.
A new application instance does not reset the total. A new UTC date starts a new
bucket; local timezone, restart and missing usage do not reset it. Existing-day
charges remain if operators reduce the configured limit below usage.

Ledger work runs in a thread within the existing total generation deadline.
SQLite's lock wait is bounded to 0.2 seconds. If cancellation happens while that
thread finishes a charge, unused allowance may remain charged, but a denied
request cannot generate for free. The bulkhead is released on cancellation.

The bucket is the attempt-admission date, not the exact time tokens execute.
A request admitted before midnight may finish after midnight. Context/output
settings must be honoured by the local runtime. This is not a proof of an exact
physical GPU-token/energy ceiling, a tokenizer-aware bound on full prompt
formatting, or usage control over requests made directly to Ollama. Different
hosts with independent ledgers each have their own limit; this does not claim a
distributed global budget. Operators deleting the ledger reset its history.

## Configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `ANSWER_DAILY_TOKEN_LIMIT` | `1000000` | Positive daily admission allowance, up to 1,000,000,000 |
| `ANSWER_DAILY_BUDGET_DB` | `state/answer-budget.sqlite3` | Persistent, writable SQLite file; relative to process working directory |

Zero/unlimited and `:memory:` are rejected. A limit smaller than one attempt
means all generation falls back. No model calls or charges occur in evidence-only
mode, for empty evidence or pending updates. The guard PR similarly bypasses
generation before this adapter, so guard refusals do not charge once combined.

Production configuration is read on startup. Keep the same ledger path mounted
across worker/container restarts. SQLite stores dates and numeric totals, not
questions, source text, user IDs or model output. SQLite files are Git-ignored.

The default full stack includes the named `answer-budget` volume and ledger path
`/answer-budget/usage.sqlite3`; no extra overlay is needed:

```sh
docker compose up -d --build
```

`docker compose down` preserves the ledger. Deleting the named volume removes
its history. The old `compose.answer-budget.yaml` remains a compatible optional
overlay. A standalone container without a mounted ledger still loses history on
replacement. The earlier Docker replacement check passed on a temporary combined
stack; final merged-stack verification remains separate.

### Long evaluation runs

The default admits only 118 attempts per UTC day. Before an 880-request rerun,
explicitly choose an evaluation allowance. For example, set this in the local
`.env` used to start the evaluation stack:

```text
ANSWER_GENERATION_MODE=ollama
OLLAMA_MODEL=llama3.2:3b
ANSWER_DAILY_TOKEN_LIMIT=25000000
```

At 8,448 per attempt this covers 880 requests even if all use the maximum three
attempts (22,302,720 units), provided prior charges that UTC day leave enough
allowance. The default retry count is two. Recalculate for different context,
output caps, prior use or extra runs. This example does not change the normal
1,000,000 default or disable enforcement. Recreate Answer after setting changes.
Record the chosen allowance and inspect `studentpath_answer_budget_rejections_total`
before and after the run; separate budget-denied fallbacks from answer-quality
results. Restarting does not clear prior usage, and process metrics reset even
though ledger usage persists. Do not delete the ledger just to conceal denials.

## Observe and demonstrate

`GET /metrics` adds:

- `studentpath_answer_budget_charged_tokens_total`: allowance successfully
  charged by this process, not the persistent all-process UTC-day total.
- `studentpath_answer_budget_rejections_total{reason="exhausted"}`.
- `studentpath_answer_budget_rejections_total{reason="unavailable"}`.

These counters reset with the process; the admission ledger does not. If the
process is cancelled/crashes after a ledger commit, its metrics may miss that
charge. Decisions always use SQLite, not the metrics counter.

With local Ollama running and llama3.2:3b already installed:

```sh
python -m scripts.demo_answer_budget --output docs/evaluation/answer-budget-NEW-RUN.json
```

This opt-in check uses a temporary one-attempt ledger: first real-model request
answers; second falls back; a new app instance sharing the exhausted ledger
still falls back with zero outgoing attempts. It never changes the normal
service ledger and will not overwrite an existing evidence file. It needs the
development dependencies because it uses FastAPI TestClient.

Long evaluation runs need a deliberately chosen allowance so exhaustion is
reported separately from answer-quality failures. The end-to-end harness uses
the running service, so configure that service before starting. The earlier
Answer-only development harness builds explicit Settings: expose/set the daily
limit and ledger there when integrating the branches before a new long run.
Do not silently disable enforcement or discard budget-triggered fallbacks.

## Evidence, 18 November 2026

- 21 new checks cover persistence, UTC boundary, concurrent independent processes,
  concurrent API requests, retries, missing usage, cancellation, unavailable
  storage, model bypass and configuration.
- Full branch suite: 378 passed, 6 optional skips, one existing warning. This
  metrics-based branch does not include the guard/refusal-label branches.
- Actual local Ollama check: answered → degraded → degraded after app restart,
  recorded in `evaluation/answer-daily-budget-2026-11-18.json`.
- The first smoke-check assertion incorrectly searched Prometheus HELP text
  instead of samples; it was corrected and the completed check passed. The
  service's persisted allowance behaviour was unchanged.
- Compose overlay validates; no Gateway/frontend/Collector/Indexer changes.

Parameter meanings: [Ollama Modelfile reference](https://docs.ollama.com/modelfile).
Reported usage fields: [Ollama chat API](https://docs.ollama.com/api/chat).

### Docker and frontend follow-up

An isolated combined PR snapshot was checked with actual local llama3.2:3b
and synthetic Collector/Indexer evidence. A 16,896 allowance admitted two
8,448-token attempt reservations. The website showed “blue” and “ten euro”;
the third question displayed the existing degraded message and source link.

After replacing only the Answer container with its named volume retained,
the next browser question still fell back. SQLite remained at 16,896; the new
process recorded one exhausted-budget denial and zero outgoing model attempts.
No Gateway or frontend code changes were needed. The website does not show a
budget meter or a distinct budget-exhaustion explanation.

Exact branch revisions, container IDs and before/after metrics are recorded in
[evidence](evaluation/answer-budget-docker-2026-11-18.json), with a
[website screenshot](evaluation/answer-budget-frontend-2026-11-18.jpg).
This verifies the temporary combined snapshot, not final merged main or
real-source answer quality.

## PR35 review follow-up

Integrated the reviewed Docker branch (#33) into this feature branch so the
default Compose stack can mount the Answer ledger automatically. PR33 remains
a merge dependency; no Gateway or Collector logic was edited in this follow-up.
The main generation allowance stays at 1,000,000; long runs require an explicit
setting and recorded budget-denial observations. SQLite lock waits over 0.2 s
can yield unavailable-ledger fallback under contention.
