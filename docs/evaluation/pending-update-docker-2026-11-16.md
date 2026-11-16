# Pending-update Docker demonstration, 16 November 2026

Passed across actual Collector, relay, RabbitMQ, Indexer, Retrieval, Gateway and
Answer processes in the isolated `studentpath-pending-demo` Compose project.
Service code based on main commit `04e5a41`. The demo configuration and scripts
were uncommitted at build time; the raw report records the runner hash.

| Phase | Affected question | Index generation | Unaffected question |
| --- | --- | --- | --- |
| before | degraded | idx-4 | degraded |
| pending | insufficient_evidence | idx-4 | degraded |
| after | degraded | idx-5 | degraded |

Observed: form source version 3 (blue), changed to version 4 (green) while the
Indexer was stopped. The affected response named that source and the actual
Collector detection timestamp, with indexed/latest versions 3/4. Fee source
remained version 1. Resuming indexing changed the active generation from idx-4
to idx-5 and returned green evidence. Request IDs were propagated in all six
saved public responses. The Indexer was left running after the successful test.

The first attempt exposed a runner issue: `docker compose start indexer`
restarted its completed seed dependency and reverted the source fixture. That
attempt did not complete recovery and is not counted as a successful run. The
runner was corrected to start only the existing Indexer container. No service
implementation was changed. Prior partial results remain in the ignored local
results directory.

Normal responses intentionally use evidence-only `degraded` mode. No Ollama
calls, generated-answer quality, frontend display or all-pending-PR integration
are demonstrated. The response itself, not a browser screenshot, is evidence of
the HTTP handover. Lexically disjoint test probes avoid unrelated retrieval
matches and do not establish production ranking quality.

See [instructions](../pending-update-demo.md) and the adjacent raw JSON report.
Re-run after the Answer PRs merge to verify the final combined submission.
