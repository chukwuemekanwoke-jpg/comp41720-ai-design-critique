from __future__ import annotations

from indexing_worker.chunking import DeterministicChunker
from indexing_worker.models import (
    DocumentUpdateEvent,
    SnapshotResponse,
)
from indexing_worker.store import IndexerStore


class SQLiteIndexBuilder:
    """
    Build an immutable index candidate from a verified snapshot.
    """

    def __init__(
        self,
        store: IndexerStore,
        chunker: DeterministicChunker | None = None,
    ) -> None:
        self.store = store
        self.chunker = chunker or DeterministicChunker()

    def build_index(
        self,
        event: DocumentUpdateEvent,
        snapshot: SnapshotResponse,
    ) -> int:
        passages = self.chunker.chunk(
            snapshot_id=snapshot.snapshot_id,
            clean_text=snapshot.clean_text,
        )

        self.store.save_passages(passages)

        return self.store.create_index_version(
            event=event,
            passages=passages,
        )
