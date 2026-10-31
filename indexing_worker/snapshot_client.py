from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from indexing_worker.models import SnapshotResponse


class SnapshotClientError(RuntimeError):
    """The Collector snapshot endpoint could not be used."""


class CollectorSnapshotClient:
    """Retrieve immutable snapshots from the Source Collector."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 5.0,
    ) -> None:
        if not base_url.strip():
            raise ValueError("base_url cannot be empty")

        if timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be positive"
            )

        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def fetch_snapshot(
        self,
        snapshot_id: str,
    ) -> SnapshotResponse:
        encoded_snapshot_id = quote(
            snapshot_id,
            safe="",
        )
        url = (
            f"{self.base_url}/snapshots/"
            f"{encoded_snapshot_id}"
        )

        request = Request(
            url=url,
            method="GET",
            headers={
                "Accept": "application/json",
            },
        )

        try:
            with urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                status = response.status
                response_body = response.read()

        except HTTPError as error:
            raise SnapshotClientError(
                "Collector returned HTTP "
                f"{error.code} for snapshot {snapshot_id}"
            ) from error

        except URLError as error:
            raise SnapshotClientError(
                "Could not connect to the Collector for "
                f"snapshot {snapshot_id}: {error.reason}"
            ) from error

        if status != 200:
            raise SnapshotClientError(
                "Collector returned unexpected HTTP "
                f"{status} for snapshot {snapshot_id}"
            )

        try:
            payload = json.loads(
                response_body.decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SnapshotClientError(
                "Collector returned invalid JSON for "
                f"snapshot {snapshot_id}"
            ) from error

        if not isinstance(payload, dict):
            raise SnapshotClientError(
                "Collector snapshot response must be a JSON object"
            )

        return SnapshotResponse.from_dict(payload)
