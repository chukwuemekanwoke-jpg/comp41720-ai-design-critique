from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Iterator

from indexing_worker.models import DocumentUpdateEvent


@dataclass(frozen=True, slots=True)
class EventRecord:
    event_id: str
    status: str
    attempt_count: int
    last_error: str | None


@dataclass(frozen=True, slots=True)
class ActiveSource:
    source_id: str
    source_version: int
    snapshot_id: str
    index_version: int


class IndexerStore:
    """Durable SQLite state owned by the Indexing Worker."""

    def __init__(self, database_path: str | Path) -> None:
        self.connection = sqlite3.connect(
            str(database_path),
            isolation_level=None,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS processed_events (
                event_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                source_version INTEGER NOT NULL,
                snapshot_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN (
                        'processing',
                        'completed',
                        'failed',
                        'obsolete'
                    )
                ),
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (source_id, source_version)
            );

            CREATE TABLE IF NOT EXISTS source_state (
                source_id TEXT PRIMARY KEY,
                source_version INTEGER NOT NULL,
                snapshot_id TEXT NOT NULL,
                index_version INTEGER NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Run related SQLite operations atomically."""

        self.connection.execute("BEGIN IMMEDIATE")

        try:
            yield
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def get_event(self, event_id: str) -> EventRecord | None:
        row = self.connection.execute(
            """
            SELECT event_id, status, attempt_count, last_error
            FROM processed_events
            WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()

        if row is None:
            return None

        return EventRecord(
            event_id=row["event_id"],
            status=row["status"],
            attempt_count=row["attempt_count"],
            last_error=row["last_error"],
        )

    def get_active_source(self, source_id: str) -> ActiveSource | None:
        row = self.connection.execute(
            """
            SELECT
                source_id,
                source_version,
                snapshot_id,
                index_version
            FROM source_state
            WHERE source_id = ?
            """,
            (source_id,),
        ).fetchone()

        if row is None:
            return None

        return ActiveSource(
            source_id=row["source_id"],
            source_version=row["source_version"],
            snapshot_id=row["snapshot_id"],
            index_version=row["index_version"],
        )

    def start_attempt(self, event: DocumentUpdateEvent) -> bool:
        """
        Start or resume processing an event.

        Returns False when the same event has already reached a final state.
        """

        with self.transaction():
            row = self.connection.execute(
                """
                SELECT status
                FROM processed_events
                WHERE event_id = ?
                """,
                (event.event_id,),
            ).fetchone()

            if row is not None and row["status"] in {
                "completed",
                "obsolete",
            }:
                return False

            self.connection.execute(
                """
                INSERT INTO processed_events (
                    event_id,
                    source_id,
                    source_version,
                    snapshot_id,
                    status,
                    attempt_count,
                    last_error
                )
                VALUES (?, ?, ?, ?, 'processing', 1, NULL)
                ON CONFLICT(event_id) DO UPDATE SET
                    status = 'processing',
                    attempt_count = attempt_count + 1,
                    last_error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    event.event_id,
                    event.source_id,
                    event.source_version,
                    event.snapshot_id,
                ),
            )

        return True

    def mark_failed(
        self,
        event_id: str,
        error_message: str,
    ) -> None:
        with self.transaction():
            cursor = self.connection.execute(
                """
                UPDATE processed_events
                SET
                    status = 'failed',
                    last_error = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE event_id = ?
                """,
                (error_message, event_id),
            )

            if cursor.rowcount != 1:
                raise KeyError(f"unknown event_id: {event_id}")

    def activate(
        self,
        event: DocumentUpdateEvent,
        index_version: int,
    ) -> bool:
        """
        Activate an event when it is newer than the current source version.

        Returns True if it became active, or False if it was obsolete.
        """

        with self.transaction():
            current = self.connection.execute(
                """
                SELECT source_version
                FROM source_state
                WHERE source_id = ?
                """,
                (event.source_id,),
            ).fetchone()

            if (
                current is not None
                and current["source_version"] >= event.source_version
            ):
                self.connection.execute(
                    """
                    UPDATE processed_events
                    SET
                        status = 'obsolete',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE event_id = ?
                    """,
                    (event.event_id,),
                )
                return False

            self.connection.execute(
                """
                INSERT INTO source_state (
                    source_id,
                    source_version,
                    snapshot_id,
                    index_version
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    source_version = excluded.source_version,
                    snapshot_id = excluded.snapshot_id,
                    index_version = excluded.index_version,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    event.source_id,
                    event.source_version,
                    event.snapshot_id,
                    index_version,
                ),
            )

            cursor = self.connection.execute(
                """
                UPDATE processed_events
                SET
                    status = 'completed',
                    last_error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE event_id = ?
                """,
                (event.event_id,),
            )

            if cursor.rowcount != 1:
                raise KeyError(
                    f"event was not started: {event.event_id}"
                )

        return True

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> IndexerStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
