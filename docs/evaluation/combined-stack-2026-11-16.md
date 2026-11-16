# Combined Answer PR and browser check, 16 November 2026

A temporary copy of main was combined with the code/contracts/tests from PRs
26, 27, 28 and 29. No PR branch was merged, rebased, committed or changed during
this check. Exact branch commits and the temporary Compose configuration are in
the adjacent JSON report. The original demonstration and combined snapshot use
separate Docker projects and volumes.

## Passed

- Combined automated suite: 393 passed, 6 optional checks skipped, one existing
  TestClient warning. These totals include evaluation, guard, metrics, resilience
  and Gateway pending-update tests together.
- Docker Collector → outbox/relay → RabbitMQ → Indexer → SQLite → Retrieval →
  Gateway → Answer → actual host Ollama: baseline form answered blue and fee
  answered ten euro. The browser displayed blue with a supplied source and idx-2.
- Stopped only this demo's Indexer; changed form to green. Gateway returned the
  fixed pending-source explanation; unaffected fee question still received an
  actual model answer. Raw source versions/detection dates were checked.
- Resumed the same Indexer container. Form answered green at source version 2
  and idx-3. Browser displayed green and the new source text/index metadata.
- Explicit override question through Gateway was policy-refused with no increase
  in outgoing model attempts. Metrics exported reported input/output usage
  (2634/178 at that observation) and active generation returned to zero.

## Frontend gap found

The API returns `abstention.message` and `affected_sources`, but existing
frontend/dist/app.js renderAnswer displays only its generic insufficient-evidence
text and no affected-source link. The pending-state screenshot records this.
No frontend code was changed. Ask the frontend owner to render these fields;
safely construct links/text as for existing source rendering. Test the fixed
explanation and canonical source URL, while retaining normal refusal behaviour.

This prevents claiming a complete user-facing pending-update demonstration.
Backend integration and real generated-answer recovery passed; display remains
follow-up work. There is also no dashboard or budget enforcement claim here.

## Limits and environment

This snapshot includes unmerged PR code and uncommitted demo helpers. It is not
the final submitted revision. Re-run from merged main after reviews. The model
was the already-installed local llama3.2:3b, reached at host.docker.internal:11434.
No official immigration pages were fetched. This is a functional demonstration,
not a load, safety or factual-accuracy benchmark. UI screenshots are evidence
of visible rendering, not proof of the API fields hidden by that UI.

Combined services remain available at http://localhost:8094 (frontend) and
http://localhost:8093/docs (Gateway). The browser connection setting should be
http://localhost:8094 to use nginx's same-origin proxy. It resets on page reload.
The configuration and code snapshot live at /private/tmp/studentpath-combined-20261116;
that temporary directory is not submission source or a replacement for merging.
