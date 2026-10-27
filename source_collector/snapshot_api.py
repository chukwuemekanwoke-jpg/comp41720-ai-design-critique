"""Read-only HTTP access to immutable Collector snapshots for the local demo."""
from __future__ import annotations

import argparse
from contextlib import closing, asynccontextmanager
import os
from pathlib import Path
import re
import sqlite3

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .collector import sha256


SNAPSHOT_ID = re.compile(r"[A-Za-z0-9_-]{1,50}:[0-9a-f]{64}")
SNAPSHOT_COLUMNS = "snapshot_id,source_id,content_sha256,cleaner_version,clean_text"


class SnapshotResponse(BaseModel):
    snapshot_id: str
    source_id: str
    content_sha256: str
    cleaner_version: str
    clean_text: str


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
