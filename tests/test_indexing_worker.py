import hashlib

import pytest


from indexing_worker.models import (
    ContractError,
    DocumentUpdateEvent,
    SnapshotResponse,
)
from indexing_worker.store import IndexerStore


def make_event_payload(
    clean_text: str = "Official information about Stamp 1G.",
    source_version: int = 1,
) -> dict:
    """Create a valid Collector event for tests."""

    content_sha256 = hashlib.sha256(
        clean_text.encode("utf-8")
    ).hexdigest()

    source_id = "S001"

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
) -> DocumentUpdateEvent:
    return DocumentUpdateEvent.from_dict(
        make_event_payload(
            clean_text=clean_text,
            source_version=source_version,
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
        assert store.activate(event, index_version=1) is True

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
            index_version=2,
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
                index_version=index_version,
            ) is True

        active = store.get_active_source("S001")
        assert active is not None
        assert active.source_version == 3
        assert active.snapshot_id == version_1_a.snapshot_id
        assert active.index_version == 3
