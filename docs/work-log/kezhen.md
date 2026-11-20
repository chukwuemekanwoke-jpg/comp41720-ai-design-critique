# Kezhen Zhang: work log

## 2026-11-20 — Indexer finalisation

### Completed with AI assistance

- Based the documentation branch on main `0179403`.
- Finalised [ADR-0002](../adr/0002-idempotent-processing-of-update-events.md):
  three identifiers, the complete-candidate publication invariant from PR #16,
  implemented fixed-delay retries, confirmed quarantine handoff, and the
  metric-only dead-letter decision with alerting deferred.
- Prepared [Q004 report text](../evaluation/q004-chunking-limitation.md),
  distinguishing the teammate-reported ranking diagnosis from independent
  evaluation and documenting the proposed structure-aware chunker.
- Verified PR #16 is merged with an independent approval and closed
  [Issue #12](https://github.com/chukwuemekanwoke-jpg/comp41720-ai-design-critique/issues/12)
  as completed. Publication and reader details remain in the
  [storage contract](../indexer-retrieval-storage.md).

### Verification

```sh
.venv/bin/python -m pytest tests/test_indexing_worker.py tests/test_indexer_consumer.py tests/test_sqlite_retrieval.py tests/test_pending_change.py -q
```

Result: **66 passed**, with the existing Starlette/httpx deprecation warning.
This includes in-process pending-change checks; it is not a live saved-snapshot
Indexer/Gateway demonstration. Documentation changes pass `git diff --check`.

PR #32 at `2656f3e97cf8118ee8727655616cf68d89865211` was separately inspected:
its eight scoring tests passed, but a threshold candidate-boundary defect was
reproduced. Kezhen reported it to Emeka in WhatsApp; Emeka reproduced and fixed
it in `1a47b96`, crediting Kezhen in the commit message.

The follow-up review at `077f0318a565f2b38df3c5719393a99111b3dfe1` ran all ten
scoring tests successfully and confirmed the original example now returns
threshold 0.91 with 2/3 correct. A remaining precision issue was reproduced:
`round(cut, 4)` can change the returned threshold without recomputing its
reported counts. Kezhen reported that issue as well; review approval is pending
its resolution.

### Saved demo evidence reviewed

- After UCD sign-in, reviewed the two original 19 November pending/recovery
  JSON records in the shared drive. U01 abstains in all five pending trials;
  U02 retains evidence without abstention in all five control trials. Recovery
  changes `idx-10`/S003 v1 to `idx-11`/S003 v2. The recovered response is
  `degraded` evidence-only fallback, not generated text. See the detailed
  [evidence review](../evaluation/adr0003-evidence-review.md). This is inspection
  of saved results, not an independent live rerun.
- Emeka confirmed the 15-minute stuck-update metric and alert are not
  implemented. [PR #38](https://github.com/chukwuemekanwoke-jpg/comp41720-ai-design-critique/pull/38)
  clarifies that they are future work, consistent with ADR-0002's metric-only
  quarantine decision. The documentation diff was reviewed; its evidence link
  depends on the files introduced by #37.
- Q004 diagnostic outputs and prototype revision are needed to reproduce the
  reported ranks; the table-aware chunker remains proposed work.
- The documentation was submitted in
  [PR #37](https://github.com/chukwuemekanwoke-jpg/comp41720-ai-design-critique/pull/37),
  approved by Emeka with all five CI checks successful, and merged into main as
  `78fac19`. This work-log follow-up updates the earlier preparation status.
