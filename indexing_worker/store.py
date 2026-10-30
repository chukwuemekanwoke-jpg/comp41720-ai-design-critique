from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Iterator

from indexing_worker.models import DocumentUpdateEvent
from indexing_worker.chunking import Passage


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


@dataclass(frozen=True, slots=True)
class IndexSource:
    index_version: int
    source_id: str
    source_version: int
    snapshot_id: str
    source_url: str
    checked_at: str


class StaleIndexCandidateError(ValueError):
    """The current index changed while a candidate was being built."""


class IndexerStore:
    """Durable SQLite state owned by the Indexing Worker."""

    def __init__(self, database_path: str | Path) -> None:
        self.connection = sqlite3.connect(
            str(database_path),
            isolation_level=None,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA busy_timeout = 5000")
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

            CREATE TABLE IF NOT EXISTS passages (
                passage_id TEXT PRIMARY KEY,
                snapshot_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                chunker_version TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (
                    snapshot_id,
                    chunker_version,
                    chunk_index
                )
            );

            CREATE INDEX IF NOT EXISTS idx_passages_snapshot
            ON passages (
                snapshot_id,
                chunker_version,
                chunk_index
            );
            CREATE TABLE IF NOT EXISTS index_versions (
                index_version INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL CHECK (
                    status IN (
                        'building',
                        'ready',
                        'active',
                        'superseded',
                        'discarded'
                    )
                ),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                base_index_version INTEGER,
                activated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS index_sources (
                index_version INTEGER NOT NULL,
                source_id TEXT NOT NULL,
                source_version INTEGER NOT NULL,
                snapshot_id TEXT NOT NULL,
                source_url TEXT NOT NULL,
                checked_at TEXT NOT NULL,
                PRIMARY KEY (
                    index_version,
                    source_id
                ),
                FOREIGN KEY (index_version)
                    REFERENCES index_versions(index_version)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS index_passages (
                index_version INTEGER NOT NULL,
                source_id TEXT NOT NULL,
                passage_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                PRIMARY KEY (
                    index_version,
                    source_id,
                    position
                ),
                UNIQUE (
                    index_version,
                    source_id,
                    passage_id
                ),
                FOREIGN KEY (index_version)
                    REFERENCES index_versions(index_version)
                    ON DELETE CASCADE,
                FOREIGN KEY (passage_id)
                    REFERENCES passages(passage_id)
            );

            CREATE TABLE IF NOT EXISTS current_index (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                index_version INTEGER NOT NULL,
                FOREIGN KEY (index_version)
                    REFERENCES index_versions(index_version)
            );

            CREATE VIEW IF NOT EXISTS published_index_versions AS
            SELECT
                index_version,
                status,
                activated_at
            FROM index_versions
            WHERE status IN ('active', 'superseded');

            CREATE VIEW IF NOT EXISTS published_passages AS
            SELECT
                versions.index_version,
                versions.status AS index_status,
                versions.activated_at,
                sources.source_id,
                sources.source_version,
                sources.snapshot_id,
                sources.source_url,
                sources.checked_at,
                mappings.passage_id,
                mappings.position,
                passages.text,
                passages.content_sha256,
                passages.chunker_version
            FROM index_versions AS versions
            JOIN index_sources AS sources
                ON sources.index_version = versions.index_version
            JOIN index_passages AS mappings
                ON mappings.index_version = sources.index_version
                AND mappings.source_id = sources.source_id
            JOIN passages
                ON passages.passage_id = mappings.passage_id
            WHERE versions.status IN ('active', 'superseded');
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
        Atomically activate a completed index candidate.

        The source state, index status, current pointer and event status
        are changed in one SQLite transaction.
        """

        with self.transaction():
            current_source = self.connection.execute(
                """
                    SELECT source_version
                    FROM source_state
                    WHERE source_id = ?
                    """,
                (event.source_id,),
            ).fetchone()

            if (
                current_source is not None
                and current_source["source_version"]
                >= event.source_version
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

                self.connection.execute(
                    """
                        UPDATE index_versions
                        SET status = 'discarded'
                        WHERE
                            index_version = ?
                            AND status IN ('building', 'ready')
                        """,
                    (index_version,),
                )

                return False

            candidate = self.connection.execute(
                """
                    SELECT status, base_index_version
                    FROM index_versions
                    WHERE index_version = ?
                    """,
                (index_version,),
            ).fetchone()

            if candidate is not None:
                if candidate["status"] != "ready":
                    raise ValueError(
                        "only a ready index version can be activated"
                    )

                indexed_source = self.connection.execute(
                    """
                        SELECT source_version, snapshot_id
                        FROM index_sources
                        WHERE
                            index_version = ?
                            AND source_id = ?
                        """,
                    (
                        index_version,
                        event.source_id,
                    ),
                ).fetchone()

                if indexed_source is None:
                    raise ValueError(
                        "index version does not contain the event source"
                    )

                if (
                    indexed_source["source_version"]
                    != event.source_version
                    or indexed_source["snapshot_id"]
                    != event.snapshot_id
                ):
                    raise ValueError(
                        "index source does not match the event"
                    )

                previous = self.connection.execute(
                    """
                        SELECT index_version
                        FROM current_index
                        WHERE singleton = 1
                        """
                ).fetchone()

                current_index_version = (
                    int(previous["index_version"])
                    if previous is not None
                    else None
                )

                if (
                    candidate["base_index_version"]
                    != current_index_version
                ):
                    raise StaleIndexCandidateError(
                        "stale index candidate: current index changed "
                        "after the candidate was built"
                    )

                if previous is not None:
                    self.connection.execute(
                        """
                            UPDATE index_versions
                            SET status = 'superseded'
                            WHERE
                                index_version = ?
                                AND status = 'active'
                            """,
                        (previous["index_version"],),
                    )

                self.connection.execute(
                    """
                        UPDATE index_versions
                        SET
                            status = 'active',
                            activated_at = CURRENT_TIMESTAMP
                        WHERE index_version = ?
                        """,
                    (index_version,),
                )

                self.connection.execute(
                    """
                        INSERT INTO current_index (
                            singleton,
                            index_version
                        )
                        VALUES (1, ?)
                        ON CONFLICT(singleton) DO UPDATE SET
                            index_version = excluded.index_version
                        """,
                    (index_version,),
                )

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

    def save_passages(
        self,
        passages: list[Passage],
    ) -> None:
        """
        Persist passages without duplicating previously indexed content.

        Reprocessing the same snapshot and chunker version is safe.
        """

        with self.transaction():
            for passage in passages:
                self.connection.execute(
                    """
                    INSERT OR IGNORE INTO passages (
                        passage_id,
                        snapshot_id,
                        chunk_index,
                        text,
                        content_sha256,
                        chunker_version
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        passage.passage_id,
                        passage.snapshot_id,
                        passage.chunk_index,
                        passage.text,
                        passage.content_sha256,
                        passage.chunker_version,
                    ),
                )

                stored = self.connection.execute(
                    """
                    SELECT
                        snapshot_id,
                        chunk_index,
                        text,
                        content_sha256,
                        chunker_version
                    FROM passages
                    WHERE passage_id = ?
                    """,
                    (passage.passage_id,),
                ).fetchone()

                if stored is None:
                    raise RuntimeError(
                        "passage was not stored"
                    )

                expected = (
                    passage.snapshot_id,
                    passage.chunk_index,
                    passage.text,
                    passage.content_sha256,
                    passage.chunker_version,
                )
                actual = (
                    stored["snapshot_id"],
                    stored["chunk_index"],
                    stored["text"],
                    stored["content_sha256"],
                    stored["chunker_version"],
                )

                if actual != expected:
                    raise ValueError(
                        "passage_id collision with different content"
                    )

    def get_passages(
        self,
        snapshot_id: str,
        chunker_version: str,
    ) -> list[Passage]:
        rows = self.connection.execute(
            """
            SELECT
                passage_id,
                snapshot_id,
                chunk_index,
                text,
                content_sha256,
                chunker_version
            FROM passages
            WHERE
                snapshot_id = ?
                AND chunker_version = ?
            ORDER BY chunk_index
            """,
            (snapshot_id, chunker_version),
        ).fetchall()

        return [
            Passage(
                passage_id=row["passage_id"],
                snapshot_id=row["snapshot_id"],
                chunk_index=row["chunk_index"],
                text=row["text"],
                content_sha256=row["content_sha256"],
                chunker_version=row["chunker_version"],
            )
            for row in rows
        ]

    def count_passages(self) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS passage_count FROM passages"
        ).fetchone()

        return int(row["passage_count"])

    def create_index_version(
        self,
        event: DocumentUpdateEvent,
        passages: list[Passage],
    ) -> int:
        """
        Build an immutable candidate index manifest.

        Creating the candidate does not make it current. Activation is a
        separate atomic operation performed only after the build succeeds.
        """

        if not passages:
            raise ValueError(
                "an index version must contain at least one passage"
            )

        if any(
            passage.snapshot_id != event.snapshot_id
            for passage in passages
        ):
            raise ValueError(
                "all passages must belong to the event snapshot"
            )

        passage_ids = [
            passage.passage_id
            for passage in passages
        ]

        if len(passage_ids) != len(set(passage_ids)):
            raise ValueError(
                "an index version cannot contain duplicate passages"
            )

        with self.transaction():
            # All passages must already exist in the passage repository.
            for passage in passages:
                stored = self.connection.execute(
                    """
                    SELECT snapshot_id
                    FROM passages
                    WHERE passage_id = ?
                    """,
                    (passage.passage_id,),
                ).fetchone()

                if stored is None:
                    raise ValueError(
                        "passage must be saved before creating "
                        "an index version"
                    )

                if stored["snapshot_id"] != event.snapshot_id:
                    raise ValueError(
                        "stored passage belongs to a different snapshot"
                    )

            current = self.connection.execute(
                """
                SELECT index_version
                FROM current_index
                WHERE singleton = 1
                """
            ).fetchone()

            base_index_version = (
                int(current["index_version"])
                if current is not None
                else None
            )
            cursor = self.connection.execute(
                """
            INSERT INTO index_versions (
                status,
                base_index_version
            )
            VALUES ('building', ?)
            """,
                (base_index_version,),
            )

            last_row_id = cursor.lastrowid

            if last_row_id is None:
                raise RuntimeError(
                    "SQLite did not return an index version"
                )

            index_version = int(last_row_id)

            if current is not None:
                current_version = current["index_version"]

                # Copy unchanged source mappings from the current index.
                self.connection.execute(
                    """
                    INSERT INTO index_sources (
                        index_version,
                        source_id,
                        source_version,
                        snapshot_id,
                        source_url,
                        checked_at
                    )
                    SELECT
                        ?,
                        source_id,
                        source_version,
                        snapshot_id,
                        source_url,
                        checked_at
                    FROM index_sources
                    WHERE
                        index_version = ?
                        AND source_id != ?
                    """,
                    (
                        index_version,
                        current_version,
                        event.source_id,
                    ),
                )

                # Copy unchanged passage mappings.
                self.connection.execute(
                    """
                    INSERT INTO index_passages (
                        index_version,
                        source_id,
                        passage_id,
                        position
                    )
                    SELECT
                        ?,
                        source_id,
                        passage_id,
                        position
                    FROM index_passages
                    WHERE
                        index_version = ?
                        AND source_id != ?
                    """,
                    (
                        index_version,
                        current_version,
                        event.source_id,
                    ),
                )

            self.connection.execute(
                """
                INSERT INTO index_sources (
                    index_version,
                    source_id,
                    source_version,
                    snapshot_id,
                    source_url,
                    checked_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    index_version,
                    event.source_id,
                    event.source_version,
                    event.snapshot_id,
                    event.source_url,
                    event.checked_at,
                ),
            )

            for position, passage in enumerate(passages):
                self.connection.execute(
                    """
                    INSERT INTO index_passages (
                        index_version,
                        source_id,
                        passage_id,
                        position
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        index_version,
                        event.source_id,
                        passage.passage_id,
                        position,
                    ),
                )

            self.connection.execute(
                """
                UPDATE index_versions
                SET status = 'ready'
                WHERE index_version = ?
                """,
                (index_version,),
            )

        return index_version

    def discard_index_version(
        self,
        index_version: int,
    ) -> bool:
        """Hide an unpublished candidate that can no longer be activated."""

        with self.transaction():
            cursor = self.connection.execute(
                """
                UPDATE index_versions
                SET status = 'discarded'
                WHERE
                    index_version = ?
                    AND status IN ('building', 'ready')
                """,
                (index_version,),
            )

        return cursor.rowcount == 1

    def get_index_status(
        self,
        index_version: int,
    ) -> str | None:
        row = self.connection.execute(
            """
            SELECT status
            FROM index_versions
            WHERE index_version = ?
            """,
            (index_version,),
        ).fetchone()

        if row is None:
            return None

        return str(row["status"])

    def get_current_index_version(self) -> int | None:
        row = self.connection.execute(
            """
            SELECT index_version
            FROM current_index
            WHERE singleton = 1
            """
        ).fetchone()

        if row is None:
            return None

        return int(row["index_version"])

    def get_index_source(
        self,
        index_version: int,
        source_id: str,
    ) -> IndexSource | None:
        row = self.connection.execute(
            """
            SELECT
                index_version,
                source_id,
                source_version,
                snapshot_id,
                source_url,
                checked_at
            FROM index_sources
            WHERE
                index_version = ?
                AND source_id = ?
            """,
            (index_version, source_id),
        ).fetchone()

        if row is None:
            return None

        return IndexSource(
            index_version=row["index_version"],
            source_id=row["source_id"],
            source_version=row["source_version"],
            snapshot_id=row["snapshot_id"],
            source_url=row["source_url"],
            checked_at=row["checked_at"],
        )

    def get_index_passage_ids(
        self,
        index_version: int,
        source_id: str,
    ) -> list[str]:
        rows = self.connection.execute(
            """
            SELECT passage_id
            FROM index_passages
            WHERE
                index_version = ?
                AND source_id = ?
            ORDER BY position
            """,
            (index_version, source_id),
        ).fetchall()

        return [
            str(row["passage_id"])
            for row in rows
        ]

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> IndexerStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
