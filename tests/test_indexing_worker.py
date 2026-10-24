import hashlib

import pytest

from indexing_worker.models import (
    ContractError,
    DocumentUpdateEvent,
    SnapshotResponse,
)


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
