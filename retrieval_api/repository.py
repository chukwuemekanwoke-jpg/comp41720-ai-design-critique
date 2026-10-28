"""Storage boundary: resolve one immutable, committed snapshot per request.

A future SQLite adapter must read the pointer and snapshot within a read
transaction (or equivalent retention guarantee). No indexer schema is assumed.
"""
from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Protocol


class IndexUnavailable(Exception):
    """No committed active index, or storage cannot be read."""


class IndexVersionNotFound(Exception):
    """The requested committed version is absent or has been pruned."""


@dataclass(frozen=True)
class Passage:
    passage_id: str
    source_id: str
    snapshot_id: str
    source_version: int
    url: str
    text: str


@dataclass(frozen=True)
class IndexSnapshot:
    index_version: str
    last_success_at: datetime
    passages: tuple[Passage, ...]

    def __post_init__(self):
        if not self.index_version.strip():
            raise ValueError("Index version must be nonempty")
        if self.last_success_at.utcoffset() is None:
            raise ValueError("Freshness timestamp must include a timezone")
        object.__setattr__(self, "passages", tuple(self.passages))
        if len({p.passage_id for p in self.passages}) != len(self.passages):
            raise ValueError("Passage IDs must be unique within an index")


class PassageRepository(Protocol):
    def pin(self, index_version: str | None = None) -> IndexSnapshot:
        """Resolve active once, or an explicit version; return an immutable view.

        Never expose staged builds or silently fall back from a missing version.
        Raise IndexUnavailable for read failures, IndexVersionNotFound for an
        absent explicit version. Keep all provenance and freshness in this view.
        """
        ...


class InMemoryPassageRepository:
    """Thread-safe demo/test adapter with atomic publication and activation."""

    def __init__(self):
        self._versions: dict[str, IndexSnapshot] = {}
        self._active: str | None = None
        self._lock = RLock()

    def publish(self, snapshot: IndexSnapshot, *, activate: bool = True) -> None:
        with self._lock:
            if snapshot.index_version in self._versions:
                raise ValueError("Committed index versions are immutable")
            self._versions[snapshot.index_version] = snapshot
            if activate:
                self._active = snapshot.index_version

    def activate(self, index_version: str) -> None:
        with self._lock:
            if index_version not in self._versions:
                raise IndexVersionNotFound(index_version)
            self._active = index_version

    def pin(self, index_version: str | None = None) -> IndexSnapshot:
        with self._lock:
            version = self._active if index_version is None else index_version
            if version is None:
                raise IndexUnavailable()
            try:
                return self._versions[version]
            except KeyError:
                raise IndexVersionNotFound(version) from None
