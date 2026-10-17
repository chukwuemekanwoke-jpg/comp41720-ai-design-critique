# Architecture Decision Records

Draft ADRs for StudentPath. Each is a proposal for the service owner to review,
change and sign off. The brief asks for five separate one-page ADRs.

| ADR | Decision | Service | Owner | Status |
| --- | --- | --- | --- | --- |
| [0001](0001-change-detection-and-snapshot-versioning.md) | Change detection and snapshot versioning | Source collector | TBD | Draft |
| [0002](0002-idempotent-processing-of-update-events.md) | Idempotent processing of update events | Indexing worker | TBD | Draft |
| [0003](0003-consistency-during-reindex.md) | Consistency during re-index | Retrieval API | TBD | Draft |
| [0004](0004-model-timeout-and-local-fallback.md) | Model timeout and local fallback | Answer service | TBD | Draft |
| [0005](0005-observability-and-answer-quality-checks.md) | Observability and answer-quality checks | Gateway and evaluation | TBD | Draft |

The service split is in [../architecture.md](../architecture.md).
