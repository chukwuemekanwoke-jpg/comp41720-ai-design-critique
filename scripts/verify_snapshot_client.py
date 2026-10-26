"""Exercise this Collector over real HTTP using a separately checked-out Indexer.

Run from the repository root with --indexer-root pointing to PR #4's checkout.
Does not merge or modify the Indexer. RabbitMQ is not involved in this check.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import socket
import sys
import tempfile
from threading import Thread
import time

import uvicorn

# Support running as `python scripts/verify_snapshot_client.py` from a checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source_collector.collector import Collector
from source_collector.snapshot_api import create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--indexer-root", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()
    root = args.indexer_root.resolve()
    if not (root / "indexing_worker" / "snapshot_client.py").is_file():
        parser.error("--indexer-root must contain indexing_worker/snapshot_client.py")
    sys.path.insert(1, str(root))
    from indexing_worker.index import SQLiteIndexBuilder
    from indexing_worker.models import DocumentUpdateEvent
    from indexing_worker.snapshot_client import CollectorSnapshotClient
    from indexing_worker.store import IndexerStore
    from indexing_worker.worker import IndexingWorker, ProcessingAction

    args.work_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.work_dir) as directory:
        directory = Path(directory)
        collector_db = directory / "collector.sqlite3"
        with closing(Collector(collector_db)) as collector:
            for text in ("Café 학생 A", "Synthetic B", "Café 학생 A"):
                collector.collect("S001", "https://www.irishimmigration.ie/test/",
                                  lambda _, text=text: f"<main><p>{text}</p></main>")
            events = [DocumentUpdateEvent.from_dict(event) for event in collector.pending_events()]

        with closing(socket.socket()) as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(create_app(collector_db), log_level="error"))
            thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 10
                while not server.started:
                    if not thread.is_alive() or time.monotonic() >= deadline:
                        raise RuntimeError("HTTP server failed to start")
                    time.sleep(0.02)
                client = CollectorSnapshotClient(f"http://127.0.0.1:{port}")
                with IndexerStore(directory / "indexer.sqlite3") as store:
                    worker = IndexingWorker(store, client, SQLiteIndexBuilder(store))
                    for event in events:
                        result = worker.process(event)
                        assert result.action == ProcessingAction.ACK_COMPLETED, result
                    assert worker.process(events[-1]).action == ProcessingAction.ACK_DUPLICATE
                    active = store.get_active_source("S001")
                    assert active.source_version == 3
                    assert active.snapshot_id == events[0].snapshot_id
                    assert store.count_passages() == 2
                    # A fresh event with an older version is covered by PR #4's tests.
                print(json.dumps({"result": "passed", "transport": "real HTTP", "indexed_versions": [1, 2, 3],
                                  "checks": ["encoded snapshot path", "UTF-8 SHA-256 verification",
                                             "A-B-A activation", "passage reuse", "duplicate event"]}))
            finally:
                server.should_exit = True
                thread.join(timeout=10)
                if thread.is_alive():
                    raise RuntimeError("HTTP server did not stop")


if __name__ == "__main__":
    main()
