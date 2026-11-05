"""Read-only HTTP access to immutable Collector snapshots for the local demo."""
from __future__ import annotations

import argparse
from contextlib import closing, asynccontextmanager
import os
from pathlib import Path
import re
import sqlite3
from datetime import timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .collector import sha256, parse_timestamp


SNAPSHOT_ID = re.compile(r"[A-Za-z0-9_-]{1,50}:[0-9a-f]{64}")
SOURCE_ID = re.compile(r"[A-Za-z0-9_-]{1,50}")
SNAPSHOT_COLUMNS = "snapshot_id,source_id,content_sha256,cleaner_version,clean_text"


class SnapshotResponse(BaseModel):
    snapshot_id: str
    source_id: str
    content_sha256: str
    cleaner_version: str
    clean_text: str


class SourceStatusResponse(BaseModel):
    source_id: str
    source_version: int
    snapshot_id: str | None
    detected_at: str | None
    last_success_at: str | None
    last_attempt_at: str | None
    last_error: str | None


def source_status_payload(row: sqlite3.Row) -> dict:
    """Reject inconsistent confirmed state; expose only a safe error summary."""
    source_id, version = row["source_id"], row["source_version"]
    snapshot_id = row["latest_snapshot_id"]
    if type(version) is not int or version < 0 or not SOURCE_ID.fullmatch(source_id):
        raise ValueError("Invalid source identity/version")
    if version == 0:
        if any(row[key] is not None for key in
               ("latest_hash", "latest_snapshot_id", "detected_at", "last_success_at")):
            raise ValueError("Unconfirmed source has confirmed state")
    elif (not snapshot_id or not SNAPSHOT_ID.fullmatch(snapshot_id)
          or snapshot_id != f'{source_id}:{row["latest_hash"]}'
          or row["snapshot_source_id"] != source_id
          or row["snapshot_hash"] != row["latest_hash"]
          or row["last_success_at"] is None or row["last_attempt_at"] is None):
        raise ValueError("Confirmed source has inconsistent snapshot identity")
    timestamps = {}
    for field in ("detected_at", "last_success_at", "last_attempt_at"):
        value = row[field]
        timestamps[field] = (parse_timestamp(value).astimezone(timezone.utc).isoformat()
                             if value is not None else None)
    return {"source_id": source_id, "source_version": version, "snapshot_id": snapshot_id,
            **timestamps, "last_error": "Latest source fetch or content extraction failed."
            if row["last_error"] is not None else None}


def open_readonly(db_path: Path) -> sqlite3.Connection:
    # mode=ro both prevents writes and refuses to create a missing database.
    connection = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    return connection


def create_app(db_path: str | Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        path = Path(db_path or os.environ.get("COLLECTOR_DB", "collector.sqlite3")).resolve()
        try:
            with closing(open_readonly(path)) as connection:
                connection.execute(f"SELECT {SNAPSHOT_COLUMNS} FROM snapshots LIMIT 0")
        except sqlite3.Error:
            raise RuntimeError("Snapshot API requires an existing Collector database with snapshots schema") from None
        app.state.db_path = path
        yield

    app = FastAPI(title="StudentPath Collector Snapshot API", lifespan=lifespan)

    @app.get("/snapshots/{snapshot_id}", response_model=SnapshotResponse)
    def get_snapshot(snapshot_id: str):
        if not SNAPSHOT_ID.fullmatch(snapshot_id):
            raise HTTPException(400, "Invalid snapshot_id")
        try:
            # A request owns its connection, avoiding cross-thread SQLite usage.
            with closing(open_readonly(app.state.db_path)) as connection:
                row = connection.execute(
                    f"SELECT {SNAPSHOT_COLUMNS} FROM snapshots WHERE snapshot_id=?",
                    (snapshot_id,),
                ).fetchone()
        except sqlite3.Error:
            raise HTTPException(503, "Snapshot store unavailable") from None
        if row is None:
            raise HTTPException(404, "Snapshot not found")
        payload = dict(row)
        # Never serve inconsistent text as a successful immutable snapshot.
        if (payload["snapshot_id"] != f'{payload["source_id"]}:{payload["content_sha256"]}'
                or sha256(payload["clean_text"]) != payload["content_sha256"]):
            raise HTTPException(500, "Snapshot integrity check failed")
        return payload

    @app.get("/sources/{source_id}/status", response_model=SourceStatusResponse)
    def get_source_status(source_id: str):
        if not SOURCE_ID.fullmatch(source_id):
            raise HTTPException(400, "Invalid source_id")
        try:
            with closing(open_readonly(app.state.db_path)) as connection:
                # One SELECT gives a consistent view even during collection.
                row = connection.execute("""SELECT s.source_id,s.source_version,
                    s.latest_snapshot_id,s.latest_hash,s.detected_at,s.last_success_at,
                    s.last_attempt_at,s.last_error,p.source_id AS snapshot_source_id,
                    p.content_sha256 AS snapshot_hash FROM sources s
                    LEFT JOIN snapshots p ON p.snapshot_id=s.latest_snapshot_id
                    WHERE s.source_id=?""", (source_id,)).fetchone()
        except sqlite3.Error:
            raise HTTPException(503, "Source status store unavailable") from None
        if row is None:
            raise HTTPException(404, "Source not found")
        try:
            return source_status_payload(row)
        except (ValueError, TypeError):
            raise HTTPException(500, "Source status integrity check failed") from None

    return app


app = create_app()


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("COLLECTOR_DB", "collector.sqlite3"))
    parser.add_argument("--host", default="127.0.0.1", help="Local demo binding; use 0.0.0.0 only on a trusted network")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    uvicorn.run(create_app(args.db), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
