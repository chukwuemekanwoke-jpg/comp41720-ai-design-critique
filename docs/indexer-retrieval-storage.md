# Indexer–Retrieval SQLite publication contract

Status: implementation draft for Issue #12.

## Ownership and access

The Indexing Worker is the only SQLite writer. It enables WAL mode and a
five-second busy timeout. Retrieval opens the same persistent database using a
read-only SQLite URI (`file:<path>?mode=ro`) and must not import or call Indexer
implementation code.

Retrieval must resolve the requested generation and read all of its passages in
one read transaction. For an unpinned request, it resolves `current_index` once
and keeps that generation for the complete request. It must not re-read the
pointer after ranking or while Answer is running.

## Published generations

`index_versions` uses an internal positive integer key. The HTTP representation
is `idx-<integer>` with no zero padding, for example `idx-12`. Retrieval rejects
malformed or missing explicit versions; it never silently falls back to the
current generation.

The stable read surface is:

- `current_index`: the single active generation pointer;
- `published_index_versions`: only `active` and retained `superseded` rows;
- `published_passages`: passages and provenance for those published rows.

`building`, `ready`, and `discarded` generations are deliberately absent from
the published views. Candidate construction is therefore invisible. Activation
changes the old status, new status, source state, current pointer, and event
state in one SQLite transaction.

All successfully published generations are retained for the local prototype.
Automated pruning is future work. A retained `superseded` generation remains
available for an explicitly pinned retrieval.

## Passage and source fields

Each `published_passages` row provides:

- `index_version`, `index_status`, and `activated_at`;
- `source_id`, `source_version`, `snapshot_id`, canonical `source_url`, and the
  Collector event's `checked_at` timestamp;
- `passage_id`, `position`, exact passage `text`, content SHA-256, and
  `chunker_version`.

Passage IDs are deterministic hashes of immutable snapshot identity, chunker
version, chunk position, and passage content. A content reversion A → B → A can
reuse A's passages while the newer source version still becomes active.

The default chunker uses at most 120 words, 20 overlapping words, and a hard
4,000-character limit per passage. Its version is `word-char-window-v2`.

## Freshness

The agreed default freshness interval is 300 seconds and must remain
configurable. `checked_at` is immutable provenance: it records the successful
Collector check that produced the indexed snapshot.

One limitation remains explicit. The Collector can successfully re-check
unchanged content and update its own `last_success_at` without emitting a new
document-update event. The Indexer therefore cannot derive that later timestamp
from the current event contract. Until the team chooses a freshness-status API
or freshness event, Retrieval must not claim that stored `checked_at` represents
a later unchanged check. This does not affect atomic publication or evidence
identity.

## Reader transaction outline

For an unpinned request:

1. begin a SQLite read transaction;
2. read `current_index.index_version` once;
3. verify that version exists in `published_index_versions`;
4. read its rows from `published_passages` in `source_id, position` order;
5. commit the read transaction and keep the resulting immutable in-memory view
   for ranking and Answer orchestration.

For an explicit `idx-N`, parse `N`, verify it is present in
`published_index_versions`, and read that exact generation in the same manner.
