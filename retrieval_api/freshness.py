"""Pending-change detection against Collector source status (ADR-0003).

A source has a pending change when the Collector has detected a newer
`source_version` than the one in the generation Retrieval is reading. Fetch
errors never count as changes: they leave the Collector's version unchanged.
Missing or stale status means freshness cannot be confirmed, which is a
warning, never an abstention.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from threading import Event, Lock
from typing import Callable, Iterable

import httpx

from .repository import Passage

log = logging.getLogger(__name__)

# ADR-0003 proposals; confirm with the team before relying on them.
STATUS_MAX_AGE = timedelta(seconds=60)
POLL_INTERVAL_SECONDS = 10.0


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class SourceStatus:
    source_id: str
    source_version: int
    detected_at: str | None


@dataclass(frozen=True)
class PendingSource:
    source_id: str
    indexed_source_version: int
    latest_source_version: int
    detected_at: str | None


@dataclass(frozen=True)
class FreshnessReport:
    pending: tuple[PendingSource, ...]
    confirmed: bool


class SourceStatusCache:
    """Latest known status per source; entries older than max_age are ignored."""

    def __init__(self, max_age: timedelta = STATUS_MAX_AGE,
                 clock: Callable[[], datetime] = utc_now):
        self._max_age = max_age
        self._clock = clock
        self._lock = Lock()
        self._entries: dict[str, tuple[SourceStatus, datetime]] = {}

    def put(self, status: SourceStatus) -> None:
        with self._lock:
            self._entries[status.source_id] = (status, self._clock())

    def forget(self, source_id: str) -> None:
        with self._lock:
            self._entries.pop(source_id, None)

    def get(self, source_id: str) -> SourceStatus | None:
        with self._lock:
            entry = self._entries.get(source_id)
        if entry is None or self._clock() - entry[1] > self._max_age:
            return None
        return entry[0]


def assess(passages: Iterable[Passage], cache: SourceStatusCache | None) -> FreshnessReport:
    """Compare each retrieved source's indexed version with the Collector's latest."""
    indexed: dict[str, int] = {}
    for passage in passages:
        # One generation holds one version per source; take the oldest to be safe.
        indexed[passage.source_id] = min(passage.source_version,
                                         indexed.get(passage.source_id, passage.source_version))
    pending: list[PendingSource] = []
    confirmed = True
    for source_id, version in sorted(indexed.items()):
        status = cache.get(source_id) if cache is not None else None
        if status is None:
            confirmed = False
        elif status.source_version > version:
            pending.append(PendingSource(source_id, version, status.source_version, status.detected_at))
    return FreshnessReport(tuple(pending), confirmed)


class CollectorStatusClient:
    """Reads `GET /sources/{source_id}/status` from the Collector API."""

    def __init__(self, base_url: str, timeout: float = 2.0, transport=None):
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout,
                                    transport=transport, trust_env=False, follow_redirects=False)

    def fetch(self, source_id: str) -> SourceStatus | None:
        """Return the status, None if the Collector does not know the source."""
        response = self._client.get(f"/sources/{source_id}/status")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        body = response.json()
        if body.get("source_id") != source_id or type(body.get("source_version")) is not int:
            raise ValueError("Collector returned status for a different or malformed source")
        return SourceStatus(source_id, body["source_version"], body.get("detected_at"))

    def close(self) -> None:
        self._client.close()


class StatusPoller:
    """Refreshes the cache for the sources in the active generation."""

    def __init__(self, cache: SourceStatusCache, fetch: Callable[[str], SourceStatus | None],
                 source_ids: Callable[[], Iterable[str]]):
        self._cache = cache
        self._fetch = fetch
        self._source_ids = source_ids

    def poll_once(self) -> None:
        for source_id in self._source_ids():
            try:
                status = self._fetch(source_id)
            except Exception as error:  # Keep the old entry; it ages out after max_age.
                log.warning("Source status unavailable for %s: %s", source_id, type(error).__name__)
                continue
            if status is None:
                self._cache.forget(source_id)
            else:
                self._cache.put(status)

    def run(self, stop: Event, interval: float = POLL_INTERVAL_SECONDS) -> None:
        while not stop.is_set():
            try:
                self.poll_once()
            except Exception as error:  # e.g. the index is unreadable; try again next cycle
                log.warning("Status poll failed: %s", type(error).__name__)
            stop.wait(interval)
