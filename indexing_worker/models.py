from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import re
from typing import Any
from urllib.parse import urlparse


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    """Raised when Collector data does not satisfy the agreed contract."""


def require_text(payload: dict[str, Any], field: str) -> str:
    """Return a required non-empty string field."""

    value = payload.get(field)

    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a non-empty string")

    return value


def validate_sha256(value: str, field: str) -> None:
    """Check that a value is a lowercase hexadecimal SHA-256 digest."""

    if not SHA256_PATTERN.fullmatch(value):
        raise ContractError(
            f"{field} must be a 64-character lowercase SHA-256 digest"
        )


@dataclass(frozen=True, slots=True)
class DocumentUpdateEvent:
    """Document-update event received from RabbitMQ."""

    event_id: str
    source_id: str
    source_version: int
    snapshot_id: str
    content_sha256: str
    source_url: str
    checked_at: str
    cleaner_version: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DocumentUpdateEvent:
        """Validate a dictionary and convert it into an event object."""

        if not isinstance(payload, dict):
            raise ContractError("event payload must be a dictionary")

        event_id = require_text(payload, "event_id")
        source_id = require_text(payload, "source_id")
        snapshot_id = require_text(payload, "snapshot_id")
        content_sha256 = require_text(payload, "content_sha256")
        source_url = require_text(payload, "source_url")
        checked_at = require_text(payload, "checked_at")
        cleaner_version = require_text(payload, "cleaner_version")

        source_version = payload.get("source_version")
        if (
            not isinstance(source_version, int)
            or isinstance(source_version, bool)
            or source_version <= 0
        ):
            raise ContractError("source_version must be a positive integer")

        expected_event_id = f"{source_id}:{source_version}"
        if event_id != expected_event_id:
            raise ContractError(
                f"event_id must be {expected_event_id}, got {event_id}"
            )

        validate_sha256(content_sha256, "content_sha256")

        expected_snapshot_id = f"{source_id}:{content_sha256}"
        if snapshot_id != expected_snapshot_id:
            raise ContractError(
                "snapshot_id must contain source_id and content_sha256"
            )

        parsed_url = urlparse(source_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise ContractError("source_url must be a valid HTTPS URL")

        try:
            datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ContractError(
                "checked_at must be a valid ISO-8601 timestamp"
            ) from error

        return cls(
            event_id=event_id,
            source_id=source_id,
            source_version=source_version,
            snapshot_id=snapshot_id,
            content_sha256=content_sha256,
            source_url=source_url,
            checked_at=checked_at,
            cleaner_version=cleaner_version,
        )


@dataclass(frozen=True, slots=True)
class SnapshotResponse:
    """Immutable snapshot returned by the Collector HTTP API."""

    snapshot_id: str
    source_id: str
    content_sha256: str
    cleaner_version: str
    clean_text: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SnapshotResponse:
        """Validate a snapshot API response."""

        if not isinstance(payload, dict):
            raise ContractError("snapshot response must be a dictionary")

        return cls(
            snapshot_id=require_text(payload, "snapshot_id"),
            source_id=require_text(payload, "source_id"),
            content_sha256=require_text(payload, "content_sha256"),
            cleaner_version=require_text(payload, "cleaner_version"),
            clean_text=require_text(payload, "clean_text"),
        )

    def verify_against(self, event: DocumentUpdateEvent) -> None:
        """Verify that this snapshot belongs to the supplied event."""

        if self.snapshot_id != event.snapshot_id:
            raise ContractError("snapshot_id does not match the event")

        if self.source_id != event.source_id:
            raise ContractError("source_id does not match the event")

        if self.content_sha256 != event.content_sha256:
            raise ContractError("content_sha256 does not match the event")

        if self.cleaner_version != event.cleaner_version:
            raise ContractError("cleaner_version does not match the event")

        validate_sha256(self.content_sha256, "content_sha256")

        actual_hash = hashlib.sha256(
            self.clean_text.encode("utf-8")
        ).hexdigest()

        if actual_hash != self.content_sha256:
            raise ContractError(
                "SHA-256 of clean_text does not match content_sha256"
            )
