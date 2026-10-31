from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from indexing_worker.models import (
    DocumentUpdateEvent,
    SnapshotResponse,
)
from indexing_worker.store import (
    IndexerStore,
    StaleIndexCandidateError,
)


class SnapshotClient(Protocol):
    """Interface implemented by the future Collector HTTP client."""

    def fetch_snapshot(
        self,
        snapshot_id: str,
    ) -> SnapshotResponse:
        ...


class IndexBuilder(Protocol):
    """Interface implemented by the future versioned index builder."""

    def build_index(
        self,
        event: DocumentUpdateEvent,
        snapshot: SnapshotResponse,
    ) -> int:
        """Build the next index and return its index version."""
        ...


class ProcessingAction(str, Enum):
    ACK_COMPLETED = "ack_completed"
    ACK_DUPLICATE = "ack_duplicate"
    ACK_OBSOLETE = "ack_obsolete"
    RETRY = "retry"
    DEAD_LETTER = "dead_letter"


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    event_id: str
    action: ProcessingAction
    index_version: int | None = None
    error: str | None = None


class IndexingWorker:
    """Coordinate one document-update event from receipt to activation."""

    def __init__(
        self,
        store: IndexerStore,
        snapshot_client: SnapshotClient,
        index_builder: IndexBuilder,
        max_attempts: int = 3,
        max_publication_attempts: int = 3,
    ) -> None:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")

        if max_publication_attempts <= 0:
            raise ValueError(
                "max_publication_attempts must be positive"
            )

        self.store = store
        self.snapshot_client = snapshot_client
        self.index_builder = index_builder
        self.max_attempts = max_attempts
        self.max_publication_attempts = (
            max_publication_attempts
        )

    def process(
        self,
        event: DocumentUpdateEvent,
    ) -> ProcessingResult:
        """
        Process one event and tell the RabbitMQ adapter what to do.

        This method does not acknowledge messages itself. The future RabbitMQ
        adapter converts the returned action into ACK, retry or dead-letter
        behaviour.
        """

        should_process = self.store.start_attempt(event)

        if not should_process:
            active = self.store.get_active_source(event.source_id)

            return ProcessingResult(
                event_id=event.event_id,
                action=ProcessingAction.ACK_DUPLICATE,
                index_version=(
                    active.index_version
                    if active is not None
                    else None
                ),
            )

        active = self.store.get_active_source(event.source_id)

        if (
            active is not None
            and active.source_version >= event.source_version
        ):
            self.store.activate(
                event,
                index_version=active.index_version,
            )

            return ProcessingResult(
                event_id=event.event_id,
                action=ProcessingAction.ACK_OBSOLETE,
                index_version=active.index_version,
            )

        try:
            snapshot = self.snapshot_client.fetch_snapshot(
                event.snapshot_id
            )
            snapshot.verify_against(event)
            for publication_attempt in range(
                self.max_publication_attempts
            ):
                index_version = self.index_builder.build_index(
                    event,
                    snapshot,
                )

                try:
                    activated = self.store.activate(
                        event,
                        index_version=index_version,
                    )
                except StaleIndexCandidateError:
                    discarded = self.store.discard_index_version(
                        index_version
                    )

                    if not discarded:
                        raise RuntimeError(
                            "stale index candidate could not "
                            "be discarded"
                        )

                    if (
                        publication_attempt + 1
                        >= self.max_publication_attempts
                    ):
                        raise

                    continue

                if not activated:
                    current = self.store.get_active_source(
                        event.source_id
                    )

                    return ProcessingResult(
                        event_id=event.event_id,
                        action=ProcessingAction.ACK_OBSOLETE,
                        index_version=(
                            current.index_version
                            if current is not None
                            else None
                        ),
                    )

                return ProcessingResult(
                    event_id=event.event_id,
                    action=ProcessingAction.ACK_COMPLETED,
                    index_version=index_version,
                )

            raise RuntimeError(
                "publication attempts exhausted"
            )

        except Exception as error:
            error_message = str(error) or error.__class__.__name__

            self.store.mark_failed(
                event.event_id,
                error_message,
            )

            record = self.store.get_event(event.event_id)

            if record is None:
                raise RuntimeError(
                    "failed event state was not stored"
                ) from error

            action = (
                ProcessingAction.DEAD_LETTER
                if record.attempt_count >= self.max_attempts
                else ProcessingAction.RETRY
            )

            return ProcessingResult(
                event_id=event.event_id,
                action=action,
                error=error_message,
            )
