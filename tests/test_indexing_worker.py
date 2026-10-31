import hashlib
import sqlite3

import pytest


from indexing_worker.models import (
    ContractError,
    DocumentUpdateEvent,
    SnapshotResponse,
)
from indexing_worker.store import (
    IndexerStore,
    StaleIndexCandidateError,
)

from indexing_worker.worker import (
    IndexingWorker,
    ProcessingAction,
)

from indexing_worker.chunking import DeterministicChunker

from indexing_worker.index import SQLiteIndexBuilder

from urllib.error import URLError

from indexing_worker.snapshot_client import (
    CollectorSnapshotClient,
    SnapshotClientError,
)

from indexing_worker.message_handler import (
    MessageAction,
    RabbitMessageHandler,
)
from indexing_worker.worker import ProcessingResult


def make_event_payload(
    clean_text: str = "Official information about Stamp 1G.",
    source_version: int = 1,
    source_id: str = "S001",
) -> dict:
    """Create a valid Collector event for tests."""

    content_sha256 = hashlib.sha256(
        clean_text.encode("utf-8")
    ).hexdigest()

    return {
        "event_id": f"{source_id}:{source_version}",
        "source_id": source_id,
        "source_version": source_version,
        "snapshot_id": f"{source_id}:{content_sha256}",
        "content_sha256": content_sha256,
        "source_url": (
            "https://www.irishimmigration.ie/"
            "third-level-graduate-programme/"
        ),
        "checked_at": "2026-10-24T20:00:00Z",
        "cleaner_version": "main-text-v1",
    }


def test_valid_event_and_snapshot_are_accepted() -> None:
    clean_text = "Official information about Stamp 1G."
    payload = make_event_payload(clean_text)

    event = DocumentUpdateEvent.from_dict(payload)

    snapshot = SnapshotResponse.from_dict(
        {
            "snapshot_id": event.snapshot_id,
            "source_id": event.source_id,
            "content_sha256": event.content_sha256,
            "cleaner_version": event.cleaner_version,
            "clean_text": clean_text,
        }
    )

    snapshot.verify_against(event)

    assert event.event_id == "S001:1"
    assert event.source_version == 1
    assert snapshot.clean_text == clean_text


def test_event_id_must_match_source_and_version() -> None:
    payload = make_event_payload()
    payload["event_id"] = "S001:999"

    with pytest.raises(
        ContractError,
        match="event_id must be S001:1",
    ):
        DocumentUpdateEvent.from_dict(payload)


def test_source_version_must_be_positive() -> None:
    payload = make_event_payload()
    payload["source_version"] = 0

    with pytest.raises(
        ContractError,
        match="source_version must be a positive integer",
    ):
        DocumentUpdateEvent.from_dict(payload)


def test_modified_snapshot_text_is_rejected() -> None:
    original_text = "Official information about Stamp 1G."
    event = DocumentUpdateEvent.from_dict(
        make_event_payload(original_text)
    )

    snapshot = SnapshotResponse.from_dict(
        {
            "snapshot_id": event.snapshot_id,
            "source_id": event.source_id,
            "content_sha256": event.content_sha256,
            "cleaner_version": event.cleaner_version,
            "clean_text": "This text was modified after collection.",
        }
    )

    with pytest.raises(
        ContractError,
        match="SHA-256 of clean_text does not match",
    ):
        snapshot.verify_against(event)


def make_event(
    clean_text: str = "Official information about Stamp 1G.",
    source_version: int = 1,
    source_id: str = "S001",
) -> DocumentUpdateEvent:
    return DocumentUpdateEvent.from_dict(
        make_event_payload(
            clean_text=clean_text,
            source_version=source_version,
            source_id=source_id,
        )
    )


def test_failed_event_can_be_retried(
    tmp_path,
) -> None:
    database_path = tmp_path / "indexer.sqlite3"
    event = make_event()

    with IndexerStore(database_path) as store:
        assert store.start_attempt(event) is True

        first_attempt = store.get_event(event.event_id)
        assert first_attempt is not None
        assert first_attempt.status == "processing"
        assert first_attempt.attempt_count == 1

        store.mark_failed(
            event.event_id,
            "snapshot service unavailable",
        )

        failed = store.get_event(event.event_id)
        assert failed is not None
        assert failed.status == "failed"
        assert failed.last_error == "snapshot service unavailable"

        assert store.start_attempt(event) is True

        second_attempt = store.get_event(event.event_id)
        assert second_attempt is not None
        assert second_attempt.status == "processing"
        assert second_attempt.attempt_count == 2


def test_completed_duplicate_is_skipped(
    tmp_path,
) -> None:
    database_path = tmp_path / "indexer.sqlite3"
    event = make_event()

    with IndexerStore(database_path) as store:
        assert store.start_attempt(event) is True
        index_version = build_candidate(store, event)
        assert store.activate(event, index_version=index_version) is True

        assert store.start_attempt(event) is False

        active = store.get_active_source("S001")
        assert active is not None
        assert active.source_version == 1
        assert active.index_version == 1


def test_older_event_cannot_replace_newer_version(
    tmp_path,
) -> None:
    database_path = tmp_path / "indexer.sqlite3"

    older_event = make_event(
        clean_text="Version A",
        source_version=1,
    )
    newer_event = make_event(
        clean_text="Version B",
        source_version=2,
    )

    with IndexerStore(database_path) as store:
        assert store.start_attempt(newer_event) is True
        assert store.activate(
            newer_event,
            index_version=build_candidate(store, newer_event),
        ) is True

        assert store.start_attempt(older_event) is True
        assert store.activate(
            older_event,
            index_version=1,
        ) is False

        active = store.get_active_source("S001")
        assert active is not None
        assert active.source_version == 2
        assert active.snapshot_id == newer_event.snapshot_id

        obsolete = store.get_event(older_event.event_id)
        assert obsolete is not None
        assert obsolete.status == "obsolete"


def test_content_reversion_activates_new_logical_version(
    tmp_path,
) -> None:
    database_path = tmp_path / "indexer.sqlite3"

    version_1_a = make_event(
        clean_text="Content A",
        source_version=1,
    )
    version_2_b = make_event(
        clean_text="Content B",
        source_version=2,
    )
    version_3_a = make_event(
        clean_text="Content A",
        source_version=3,
    )

    assert version_1_a.snapshot_id == version_3_a.snapshot_id
    assert version_1_a.event_id != version_3_a.event_id

    with IndexerStore(database_path) as store:
        for index_version, event in enumerate(
            [version_1_a, version_2_b, version_3_a],
            start=1,
        ):
            assert store.start_attempt(event) is True
            assert store.activate(
                event,
                index_version=build_candidate(store, event),
            ) is True

        active = store.get_active_source("S001")
        assert active is not None
        assert active.source_version == 3
        assert active.snapshot_id == version_1_a.snapshot_id
        assert active.index_version == 3


class FakeSnapshotClient:
    def __init__(
        self,
        snapshot: SnapshotResponse,
    ) -> None:
        self.snapshot = snapshot
        self.call_count = 0

    def fetch_snapshot(
        self,
        snapshot_id: str,
    ) -> SnapshotResponse:
        self.call_count += 1
        return self.snapshot


class CountingIndexBuilder(SQLiteIndexBuilder):
    def __init__(
        self,
        store: IndexerStore,
    ) -> None:
        super().__init__(store)
        self.call_count = 0

    def build_index(
        self,
        event: DocumentUpdateEvent,
        snapshot: SnapshotResponse,
    ) -> int:
        self.call_count += 1
        return super().build_index(event, snapshot)


def make_snapshot(
    event: DocumentUpdateEvent,
    clean_text: str,
) -> SnapshotResponse:
    return SnapshotResponse.from_dict(
        {
            "snapshot_id": event.snapshot_id,
            "source_id": event.source_id,
            "content_sha256": event.content_sha256,
            "cleaner_version": event.cleaner_version,
            "clean_text": clean_text,
        }
    )


def test_worker_completes_and_activates_event(
    tmp_path,
) -> None:
    clean_text = "Content A"
    event = make_event(
        clean_text=clean_text,
        source_version=1,
    )

    snapshot_client = FakeSnapshotClient(
        make_snapshot(event, clean_text)
    )

    with IndexerStore(
        tmp_path / "indexer.sqlite3"
    ) as store:
        index_builder = CountingIndexBuilder(store)

        worker = IndexingWorker(
            store=store,
            snapshot_client=snapshot_client,
            index_builder=index_builder,
        )

        result = worker.process(event)

        assert result.action == ProcessingAction.ACK_COMPLETED
        assert result.index_version == 1

        active = store.get_active_source("S001")
        assert active is not None
        assert active.source_version == 1
        assert active.snapshot_id == event.snapshot_id

        stored_event = store.get_event(event.event_id)
        assert stored_event is not None
        assert stored_event.status == "completed"


def test_worker_skips_completed_duplicate(
    tmp_path,
) -> None:
    clean_text = "Content A"
    event = make_event(
        clean_text=clean_text,
        source_version=1,
    )

    snapshot_client = FakeSnapshotClient(
        make_snapshot(event, clean_text)
    )

    with IndexerStore(
        tmp_path / "indexer.sqlite3"
    ) as store:
        index_builder = CountingIndexBuilder(store)

        worker = IndexingWorker(
            store=store,
            snapshot_client=snapshot_client,
            index_builder=index_builder,
        )

        first_result = worker.process(event)
        second_result = worker.process(event)

        assert (
            first_result.action
            == ProcessingAction.ACK_COMPLETED
        )
        assert (
            second_result.action
            == ProcessingAction.ACK_DUPLICATE
        )

        assert snapshot_client.call_count == 1
        assert index_builder.call_count == 1


def test_invalid_snapshot_retries_then_dead_letters(
    tmp_path,
) -> None:
    original_text = "Original official content"
    event = make_event(
        clean_text=original_text,
        source_version=1,
    )

    invalid_snapshot = make_snapshot(
        event,
        clean_text="Modified or damaged content",
    )

    snapshot_client = FakeSnapshotClient(invalid_snapshot)

    with IndexerStore(
        tmp_path / "indexer.sqlite3"
    ) as store:
        index_builder = CountingIndexBuilder(store)

        worker = IndexingWorker(
            store=store,
            snapshot_client=snapshot_client,
            index_builder=index_builder,
            max_attempts=3,
        )

        first_result = worker.process(event)
        second_result = worker.process(event)
        third_result = worker.process(event)

        assert first_result.action == ProcessingAction.RETRY
        assert second_result.action == ProcessingAction.RETRY
        assert (
            third_result.action
            == ProcessingAction.DEAD_LETTER
        )

        stored_event = store.get_event(event.event_id)
        assert stored_event is not None
        assert stored_event.status == "failed"
        assert stored_event.attempt_count == 3

        assert store.get_active_source("S001") is None
        assert index_builder.call_count == 0


def test_worker_skips_obsolete_event_before_fetching(
    tmp_path,
) -> None:
    newer_event = make_event(
        clean_text="Newer content",
        source_version=2,
    )
    older_event = make_event(
        clean_text="Older content",
        source_version=1,
    )

    snapshot_client = FakeSnapshotClient(
        make_snapshot(
            older_event,
            clean_text="Older content",
        )
    )

    with IndexerStore(
        tmp_path / "indexer.sqlite3"
    ) as store:
        assert store.start_attempt(newer_event) is True
        assert store.activate(
            newer_event,
            index_version=build_candidate(store, newer_event),
        ) is True

        index_builder = CountingIndexBuilder(store)

        worker = IndexingWorker(
            store=store,
            snapshot_client=snapshot_client,
            index_builder=index_builder,
        )

        result = worker.process(older_event)

        assert result.action == ProcessingAction.ACK_OBSOLETE
        assert result.index_version == 1

        assert snapshot_client.call_count == 0
        assert index_builder.call_count == 0


def test_chunker_creates_overlapping_passages() -> None:
    chunker = DeterministicChunker(
        max_words=4,
        overlap_words=1,
    )

    passages = chunker.chunk(
        snapshot_id="S001:snapshot-a",
        clean_text="one two three four five six seven",
    )

    assert [passage.text for passage in passages] == [
        "one two three four",
        "four five six seven",
    ]

    assert passages[0].chunk_index == 0
    assert passages[1].chunk_index == 1


def test_chunker_is_deterministic() -> None:
    chunker = DeterministicChunker(
        max_words=3,
        overlap_words=1,
    )

    first = chunker.chunk(
        snapshot_id="S001:snapshot-a",
        clean_text="one two three four five",
    )
    second = chunker.chunk(
        snapshot_id="S001:snapshot-a",
        clean_text="one two three four five",
    )

    assert first == second
    assert (
        [passage.passage_id for passage in first]
        == [passage.passage_id for passage in second]
    )


def test_chunker_enforces_answer_character_limit() -> None:
    chunker = DeterministicChunker(
        max_words=10,
        overlap_words=1,
        max_chars=9,
    )

    passages = chunker.chunk(
        snapshot_id="S001:snapshot-a",
        clean_text="aaaa bbbb cccc",
    )

    assert [passage.text for passage in passages] == [
        "aaaa bbbb",
        "bbbb cccc",
    ]
    assert all(
        len(passage.text) <= chunker.max_chars
        for passage in passages
    )


def test_chunker_rejects_word_over_character_limit() -> None:
    chunker = DeterministicChunker(
        max_words=10,
        overlap_words=1,
        max_chars=4,
    )

    with pytest.raises(
        ValueError,
        match="single word exceeds max_chars",
    ):
        chunker.chunk(
            snapshot_id="S001:snapshot-a",
            clean_text="abcde",
        )


def test_content_reversion_reuses_passage_ids() -> None:
    chunker = DeterministicChunker(
        max_words=3,
        overlap_words=1,
    )

    version_1_a = chunker.chunk(
        snapshot_id="S001:snapshot-a",
        clean_text="content A returns again later",
    )
    version_3_a = chunker.chunk(
        snapshot_id="S001:snapshot-a",
        clean_text="content A returns again later",
    )

    assert (
        [passage.passage_id for passage in version_1_a]
        == [passage.passage_id for passage in version_3_a]
    )


def test_chunker_rejects_empty_text() -> None:
    chunker = DeterministicChunker()

    with pytest.raises(
        ValueError,
        match="clean_text cannot be empty",
    ):
        chunker.chunk(
            snapshot_id="S001:snapshot-a",
            clean_text="   ",
        )


def test_store_persists_passages(
    tmp_path,
) -> None:
    chunker = DeterministicChunker(
        max_words=4,
        overlap_words=1,
    )

    passages = chunker.chunk(
        snapshot_id="S001:snapshot-a",
        clean_text="one two three four five six seven",
    )

    with IndexerStore(
        tmp_path / "indexer.sqlite3"
    ) as store:
        store.save_passages(passages)

        stored = store.get_passages(
            snapshot_id="S001:snapshot-a",
            chunker_version=chunker.version,
        )

        assert stored == passages
        assert store.count_passages() == 2


def test_saving_same_snapshot_does_not_duplicate_passages(
    tmp_path,
) -> None:
    chunker = DeterministicChunker(
        max_words=4,
        overlap_words=1,
    )

    version_1_a = chunker.chunk(
        snapshot_id="S001:snapshot-a",
        clean_text="one two three four five six seven",
    )
    version_3_a = chunker.chunk(
        snapshot_id="S001:snapshot-a",
        clean_text="one two three four five six seven",
    )

    with IndexerStore(
        tmp_path / "indexer.sqlite3"
    ) as store:
        store.save_passages(version_1_a)
        store.save_passages(version_3_a)

        assert store.count_passages() == 2


def test_different_snapshots_store_separate_passages(
    tmp_path,
) -> None:
    chunker = DeterministicChunker(
        max_words=4,
        overlap_words=1,
    )

    passages_a = chunker.chunk(
        snapshot_id="S001:snapshot-a",
        clean_text="content from snapshot A",
    )
    passages_b = chunker.chunk(
        snapshot_id="S001:snapshot-b",
        clean_text="content from snapshot B",
    )

    with IndexerStore(
        tmp_path / "indexer.sqlite3"
    ) as store:
        store.save_passages(passages_a)
        store.save_passages(passages_b)

        assert store.count_passages() == 2
        assert (
            passages_a[0].passage_id
            != passages_b[0].passage_id
        )


def test_create_ready_index_manifest(
    tmp_path,
) -> None:
    clean_text = (
        "one two three four five six seven"
    )
    event = make_event(
        clean_text=clean_text,
        source_version=1,
    )
    chunker = DeterministicChunker(
        max_words=4,
        overlap_words=1,
    )
    passages = chunker.chunk(
        snapshot_id=event.snapshot_id,
        clean_text=clean_text,
    )

    with IndexerStore(
        tmp_path / "indexer.sqlite3"
    ) as store:
        store.save_passages(passages)

        index_version = store.create_index_version(
            event,
            passages,
        )

        assert index_version == 1
        assert store.get_index_status(1) == "ready"

        # A ready candidate is not visible to readers yet.
        assert store.get_current_index_version() is None

        indexed_source = store.get_index_source(
            index_version=1,
            source_id="S001",
        )

        assert indexed_source is not None
        assert indexed_source.source_version == 1
        assert indexed_source.snapshot_id == event.snapshot_id
        assert indexed_source.source_url == event.source_url
        assert indexed_source.checked_at == event.checked_at

        assert store.get_index_passage_ids(
            index_version=1,
            source_id="S001",
        ) == [
            passage.passage_id
            for passage in passages
        ]


def test_published_views_hide_partial_and_retain_old_generations(
    tmp_path,
) -> None:
    database_path = tmp_path / "indexer.sqlite3"
    chunker = DeterministicChunker()

    event_v1 = make_event(
        clean_text="first published content",
        source_version=1,
    )
    event_v2 = make_event(
        clean_text="second published content",
        source_version=2,
    )

    with IndexerStore(database_path) as store:
        journal_mode = store.connection.execute(
            "PRAGMA journal_mode"
        ).fetchone()
        assert journal_mode is not None
        assert journal_mode[0] == "wal"

        assert store.start_attempt(event_v1) is True
        passages_v1 = chunker.chunk(
            event_v1.snapshot_id,
            "first published content",
        )
        store.save_passages(passages_v1)
        index_v1 = store.create_index_version(
            event_v1,
            passages_v1,
        )

        reader = sqlite3.connect(
            f"file:{database_path}?mode=ro",
            uri=True,
        )
        reader.row_factory = sqlite3.Row

        try:
            assert reader.execute(
                "SELECT * FROM published_index_versions"
            ).fetchall() == []
            assert reader.execute(
                "SELECT * FROM published_passages"
            ).fetchall() == []

            assert store.activate(event_v1, index_v1) is True

            assert store.start_attempt(event_v2) is True
            passages_v2 = chunker.chunk(
                event_v2.snapshot_id,
                "second published content",
            )
            store.save_passages(passages_v2)
            index_v2 = store.create_index_version(
                event_v2,
                passages_v2,
            )

            # The ready v2 candidate remains invisible; v1 is still current.
            visible_before_activation = reader.execute(
                """
                SELECT index_version, status
                FROM published_index_versions
                ORDER BY index_version
                """
            ).fetchall()
            assert [tuple(row) for row in visible_before_activation] == [
                (index_v1, "active"),
            ]

            assert store.activate(event_v2, index_v2) is True

            visible_after_activation = reader.execute(
                """
                SELECT index_version, status
                FROM published_index_versions
                ORDER BY index_version
                """
            ).fetchall()
            assert [tuple(row) for row in visible_after_activation] == [
                (index_v1, "superseded"),
                (index_v2, "active"),
            ]

            current = reader.execute(
                """
                SELECT index_version
                FROM current_index
                WHERE singleton = 1
                """
            ).fetchone()
            assert current is not None
            assert current["index_version"] == index_v2

            published_v2 = reader.execute(
                """
                SELECT source_url, checked_at, text
                FROM published_passages
                WHERE index_version = ?
                ORDER BY position
                """,
                (index_v2,),
            ).fetchall()
            assert [row["text"] for row in published_v2] == [
                passage.text for passage in passages_v2
            ]
            assert {
                row["source_url"] for row in published_v2
            } == {event_v2.source_url}
            assert {
                row["checked_at"] for row in published_v2
            } == {event_v2.checked_at}
        finally:
            reader.close()


def test_index_manifest_requires_saved_passages(
    tmp_path,
) -> None:
    clean_text = "official source information"
    event = make_event(
        clean_text=clean_text,
        source_version=1,
    )
    chunker = DeterministicChunker()
    passages = chunker.chunk(
        snapshot_id=event.snapshot_id,
        clean_text=clean_text,
    )

    with IndexerStore(
        tmp_path / "indexer.sqlite3"
    ) as store:
        with pytest.raises(
            ValueError,
            match="passage must be saved",
        ):
            store.create_index_version(
                event,
                passages,
            )


def test_activation_switches_current_index_atomically(
    tmp_path,
) -> None:
    clean_text = "official information version A"
    event = make_event(
        clean_text=clean_text,
        source_version=1,
    )
    chunker = DeterministicChunker()
    passages = chunker.chunk(
        snapshot_id=event.snapshot_id,
        clean_text=clean_text,
    )

    with IndexerStore(
        tmp_path / "indexer.sqlite3"
    ) as store:
        assert store.start_attempt(event) is True
        store.save_passages(passages)

        index_version = store.create_index_version(
            event,
            passages,
        )

        assert store.get_index_status(
            index_version
        ) == "ready"
        assert store.get_current_index_version() is None

        assert store.activate(
            event,
            index_version,
        ) is True

        assert store.get_index_status(
            index_version
        ) == "active"
        assert (
            store.get_current_index_version()
            == index_version
        )

        stored_event = store.get_event(event.event_id)
        assert stored_event is not None
        assert stored_event.status == "completed"


def test_new_index_supersedes_previous_index(
    tmp_path,
) -> None:
    chunker = DeterministicChunker()

    event_a = make_event(
        clean_text="official information version A",
        source_version=1,
    )
    event_b = make_event(
        clean_text="official information version B",
        source_version=2,
    )

    with IndexerStore(
        tmp_path / "indexer.sqlite3"
    ) as store:
        assert store.start_attempt(event_a) is True

        passages_a = chunker.chunk(
            snapshot_id=event_a.snapshot_id,
            clean_text="official information version A",
        )
        store.save_passages(passages_a)

        index_a = store.create_index_version(
            event_a,
            passages_a,
        )
        assert store.activate(event_a, index_a) is True

        assert store.start_attempt(event_b) is True

        passages_b = chunker.chunk(
            snapshot_id=event_b.snapshot_id,
            clean_text="official information version B",
        )
        store.save_passages(passages_b)

        index_b = store.create_index_version(
            event_b,
            passages_b,
        )
        assert store.activate(event_b, index_b) is True

        assert store.get_index_status(
            index_a
        ) == "superseded"
        assert store.get_index_status(
            index_b
        ) == "active"
        assert store.get_current_index_version() == index_b


def test_stale_candidate_cannot_replace_newer_current_index(
    tmp_path,
) -> None:
    chunker = DeterministicChunker()

    event_s001 = make_event(
        clean_text="Information from source one",
        source_version=1,
        source_id="S001",
    )
    event_s002 = make_event(
        clean_text="Information from source two",
        source_version=1,
        source_id="S002",
    )

    with IndexerStore(
        tmp_path / "indexer.sqlite3"
    ) as store:
        assert store.start_attempt(event_s001) is True
        passages_s001 = chunker.chunk(
            snapshot_id=event_s001.snapshot_id,
            clean_text="Information from source one",
        )
        store.save_passages(passages_s001)
        index_s001 = store.create_index_version(
            event_s001,
            passages_s001,
        )

        # Build S002 before S001 has been activated. Both candidates
        # are therefore based on the same empty current index.
        assert store.start_attempt(event_s002) is True
        passages_s002 = chunker.chunk(
            snapshot_id=event_s002.snapshot_id,
            clean_text="Information from source two",
        )
        store.save_passages(passages_s002)
        index_s002 = store.create_index_version(
            event_s002,
            passages_s002,
        )

        assert store.activate(
            event_s001,
            index_s001,
        ) is True

        with pytest.raises(
            ValueError,
            match="stale",
        ):
            store.activate(
                event_s002,
                index_s002,
            )

        # Rejecting the stale S002 candidate must leave S001 current.
        current_index = store.get_current_index_version()

        assert current_index is not None
        assert current_index == index_s001
        assert store.get_index_source(
            current_index,
            "S001",
        ) is not None


def test_worker_rebuilds_stale_candidate_without_broker_retry(
    tmp_path,
) -> None:
    text_s001 = "Information from source one"
    text_s002 = "Information from source two"

    event_s001 = make_event(
        clean_text=text_s001,
        source_version=1,
        source_id="S001",
    )
    event_s002 = make_event(
        clean_text=text_s002,
        source_version=1,
        source_id="S002",
    )

    with IndexerStore(
        tmp_path / "indexer.sqlite3"
    ) as store:
        real_builder = SQLiteIndexBuilder(store)

        # Build S001 but deliberately do not activate it yet.
        assert store.start_attempt(event_s001) is True
        index_s001 = real_builder.build_index(
            event_s001,
            make_snapshot(event_s001, text_s001),
        )

        class InterleavingIndexBuilder:
            def __init__(self) -> None:
                self.has_activated_s001 = False
                self.candidates: list[int] = []

            def build_index(
                self,
                event: DocumentUpdateEvent,
                snapshot: SnapshotResponse,
            ) -> int:
                candidate = real_builder.build_index(
                    event,
                    snapshot,
                )
                self.candidates.append(candidate)
                # During the first S002 build, another worker activates
                # S001, making the S002 candidate stale.
                if not self.has_activated_s001:
                    assert store.activate(
                        event_s001,
                        index_s001,
                    ) is True
                    self.has_activated_s001 = True

                return candidate

        builder = InterleavingIndexBuilder()

        worker = IndexingWorker(
            store=store,
            snapshot_client=FakeSnapshotClient(
                make_snapshot(event_s002, text_s002)
            ),
            index_builder=builder,
            max_attempts=3,
        )

        result = worker.process(event_s002)

        assert (
            result.action
            == ProcessingAction.ACK_COMPLETED
        )
        assert len(builder.candidates) == 2
        assert store.get_index_status(
            builder.candidates[0]
        ) == "discarded"
        assert store.get_index_status(
            builder.candidates[1]
        ) == "active"

        event_record = store.get_event(
            event_s002.event_id
        )
        assert event_record is not None
        assert event_record.attempt_count == 1

        current_index = store.get_current_index_version()
        assert current_index is not None

        indexed_s001 = store.get_index_source(
            current_index,
            "S001",
        )
        indexed_s002 = store.get_index_source(
            current_index,
            "S002",
        )

        assert indexed_s001 is not None
        assert indexed_s001.source_url == event_s001.source_url
        assert indexed_s001.checked_at == event_s001.checked_at
        assert indexed_s002 is not None
        assert indexed_s002.source_url == event_s002.source_url
        assert indexed_s002.checked_at == event_s002.checked_at


def test_worker_bounds_internal_stale_rebuilds(
    tmp_path,
    monkeypatch,
) -> None:
    clean_text = "Information from a continuously changing index"
    event = make_event(clean_text=clean_text)

    with IndexerStore(
        tmp_path / "indexer.sqlite3"
    ) as store:
        real_builder = SQLiteIndexBuilder(store)

        class RecordingBuilder:
            def __init__(self) -> None:
                self.candidates: list[int] = []

            def build_index(
                self,
                update: DocumentUpdateEvent,
                snapshot: SnapshotResponse,
            ) -> int:
                candidate = real_builder.build_index(
                    update,
                    snapshot,
                )
                self.candidates.append(candidate)
                return candidate

        def always_stale(
            update: DocumentUpdateEvent,
            index_version: int,
        ) -> bool:
            raise StaleIndexCandidateError(
                "stale index candidate: simulated contention"
            )

        monkeypatch.setattr(store, "activate", always_stale)
        builder = RecordingBuilder()
        worker = IndexingWorker(
            store=store,
            snapshot_client=FakeSnapshotClient(
                make_snapshot(event, clean_text)
            ),
            index_builder=builder,
            max_attempts=3,
            max_publication_attempts=2,
        )

        result = worker.process(event)

        assert result.action == ProcessingAction.RETRY
        assert len(builder.candidates) == 2
        assert all(
            store.get_index_status(candidate) == "discarded"
            for candidate in builder.candidates
        )

        event_record = store.get_event(event.event_id)
        assert event_record is not None
        assert event_record.status == "failed"
        assert event_record.attempt_count == 1


def test_real_index_builder_completes_worker_flow(
    tmp_path,
) -> None:
    clean_text = "official information about Stamp 1G"
    event = make_event(
        clean_text=clean_text,
        source_version=1,
    )
    snapshot = make_snapshot(event, clean_text)

    with IndexerStore(
        tmp_path / "indexer.sqlite3"
    ) as store:
        worker = IndexingWorker(
            store=store,
            snapshot_client=FakeSnapshotClient(snapshot),
            index_builder=SQLiteIndexBuilder(store),
        )

        result = worker.process(event)

        assert result.action == ProcessingAction.ACK_COMPLETED
        assert result.index_version == 1
        assert store.get_current_index_version() == 1
        assert store.get_index_status(1) == "active"
        assert store.count_passages() == 1


def test_real_builder_reuses_content_after_a_b_a(
    tmp_path,
) -> None:
    event_a1 = make_event(
        clean_text="Content A",
        source_version=1,
    )
    event_b = make_event(
        clean_text="Content B",
        source_version=2,
    )
    event_a3 = make_event(
        clean_text="Content A",
        source_version=3,
    )

    with IndexerStore(
        tmp_path / "indexer.sqlite3"
    ) as store:
        builder = SQLiteIndexBuilder(store)

        events_and_text = [
            (event_a1, "Content A"),
            (event_b, "Content B"),
            (event_a3, "Content A"),
        ]

        index_versions = []

        for event, clean_text in events_and_text:
            assert store.start_attempt(event) is True

            snapshot = make_snapshot(
                event,
                clean_text,
            )

            index_version = builder.build_index(
                event,
                snapshot,
            )

            assert store.activate(
                event,
                index_version,
            ) is True

            index_versions.append(index_version)

        index_a1, index_b, index_a3 = index_versions

        # Only A and B are stored; version 3 reuses A.
        assert store.count_passages() == 2

        assert (
            store.get_index_passage_ids(
                index_a1,
                "S001",
            )
            == store.get_index_passage_ids(
                index_a3,
                "S001",
            )
        )

        assert store.get_index_status(
            index_a1
        ) == "superseded"
        assert store.get_index_status(
            index_b
        ) == "superseded"
        assert store.get_index_status(
            index_a3
        ) == "active"

        active = store.get_active_source("S001")
        assert active is not None
        assert active.source_version == 3
        assert active.snapshot_id == event_a1.snapshot_id
        assert active.index_version == index_a3


class FakeHTTPResponse:
    def __init__(
        self,
        payload: bytes,
        status: int = 200,
    ) -> None:
        self.payload = payload
        self.status = status

    def read(self) -> bytes:
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


def test_collector_snapshot_client_fetches_snapshot(
    monkeypatch,
) -> None:
    clean_text = "Official information about Stamp 1G."
    event = make_event(
        clean_text=clean_text,
        source_version=1,
    )
    expected_snapshot = make_snapshot(
        event,
        clean_text,
    )

    response_payload = {
        "snapshot_id": expected_snapshot.snapshot_id,
        "source_id": expected_snapshot.source_id,
        "content_sha256": expected_snapshot.content_sha256,
        "cleaner_version": expected_snapshot.cleaner_version,
        "clean_text": expected_snapshot.clean_text,
    }

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout

        import json

        return FakeHTTPResponse(
            json.dumps(response_payload).encode("utf-8")
        )

    monkeypatch.setattr(
        "indexing_worker.snapshot_client.urlopen",
        fake_urlopen,
    )

    client = CollectorSnapshotClient(
        base_url="http://collector:8000/",
        timeout_seconds=3.0,
    )

    snapshot = client.fetch_snapshot(event.snapshot_id)

    assert snapshot == expected_snapshot
    assert captured["timeout"] == 3.0
    assert captured["url"].startswith(
        "http://collector:8000/snapshots/"
    )
    assert "%3A" in captured["url"]


def test_collector_snapshot_client_reports_connection_failure(
    monkeypatch,
) -> None:
    def failing_urlopen(request, timeout):
        raise URLError("connection refused")

    monkeypatch.setattr(
        "indexing_worker.snapshot_client.urlopen",
        failing_urlopen,
    )

    client = CollectorSnapshotClient(
        base_url="http://collector:8000",
    )

    with pytest.raises(
        SnapshotClientError,
        match="Could not connect to the Collector",
    ):
        client.fetch_snapshot("S001:snapshot-a")


def test_collector_snapshot_client_rejects_invalid_json(
    monkeypatch,
) -> None:
    def fake_urlopen(request, timeout):
        return FakeHTTPResponse(
            b"this is not JSON"
        )

    monkeypatch.setattr(
        "indexing_worker.snapshot_client.urlopen",
        fake_urlopen,
    )

    client = CollectorSnapshotClient(
        base_url="http://collector:8000",
    )

    with pytest.raises(
        SnapshotClientError,
        match="invalid JSON",
    ):
        client.fetch_snapshot("S001:snapshot-a")


class StubWorker:
    def __init__(
        self,
        action: ProcessingAction,
        error: str | None = None,
    ) -> None:
        self.action = action
        self.error = error

    def process(
        self,
        event: DocumentUpdateEvent,
    ) -> ProcessingResult:
        return ProcessingResult(
            event_id=event.event_id,
            action=self.action,
            error=self.error,
        )


def event_body(
    clean_text: str = "Official information",
) -> bytes:
    import json

    return json.dumps(
        make_event_payload(clean_text)
    ).encode("utf-8")


@pytest.mark.parametrize(
    "processing_action",
    [
        ProcessingAction.ACK_COMPLETED,
        ProcessingAction.ACK_DUPLICATE,
        ProcessingAction.ACK_OBSOLETE,
    ],
)
def test_message_handler_acknowledges_final_success(
    processing_action,
) -> None:
    handler = RabbitMessageHandler(
        StubWorker(processing_action)
    )

    decision = handler.handle(event_body())

    assert decision.action == MessageAction.ACK
    assert decision.event_id == "S001:1"


def test_message_handler_requeues_transient_failure() -> None:
    handler = RabbitMessageHandler(
        StubWorker(
            ProcessingAction.RETRY,
            error="Collector unavailable",
        )
    )

    decision = handler.handle(event_body())

    assert decision.action == MessageAction.REQUEUE
    assert decision.error == "Collector unavailable"


def test_message_handler_dead_letters_exhausted_failure() -> None:
    handler = RabbitMessageHandler(
        StubWorker(
            ProcessingAction.DEAD_LETTER,
            error="retry limit reached",
        )
    )

    decision = handler.handle(event_body())

    assert decision.action == MessageAction.DEAD_LETTER
    assert decision.event_id == "S001:1"


def test_message_handler_dead_letters_invalid_json() -> None:
    handler = RabbitMessageHandler(
        StubWorker(ProcessingAction.ACK_COMPLETED)
    )

    decision = handler.handle(b"not valid JSON")

    assert decision.action == MessageAction.DEAD_LETTER
    assert decision.event_id is None
    assert decision.error is not None


def build_candidate(store, event):
    passages = DeterministicChunker().chunk(event.snapshot_id, "Fixture passage")
    store.save_passages(passages)
    return store.create_index_version(event, passages)


def test_missing_candidate_leaves_event_retryable(tmp_path):
    event = make_event()
    with IndexerStore(tmp_path / "indexer.sqlite3") as store:
        store.start_attempt(event)
        with pytest.raises(ValueError, match="index version does not exist"):
            store.activate(event, 999)
        assert store.get_current_index_version() is None
        assert store.get_active_source(event.source_id) is None
        assert store.get_event(event.event_id).status == "processing"
        assert store.start_attempt(event) is True
        candidate = build_candidate(store, event)
        assert store.activate(event, candidate) is True
        assert store.get_current_index_version() == candidate
        assert store.start_attempt(event) is False
