from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import sqlite3
from urllib.parse import quote

from fastapi.testclient import TestClient
import pytest

from source_collector.collector import Collector
from source_collector.snapshot_api import create_app, open_readonly


@pytest.fixture
def collected(tmp_path):
    path = tmp_path / "collector.sqlite3"
    with closing(Collector(path)) as collector:
        collector.collect("S001", "https://www.irishimmigration.ie/test/",
                          lambda _: "<main><h1>Synthetic</h1><p>Café 학생 — original</p></main>")
        event = collector.pending_events()[0]
        text = collector.db.execute("SELECT clean_text FROM snapshots").fetchone()[0]
    return path, event, text


def test_encoded_snapshot_returns_exact_utf8_content_and_contract(collected):
    path, event, text = collected
    with TestClient(create_app(path)) as client:
        response = client.get("/snapshots/" + quote(event["snapshot_id"], safe=""))
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "snapshot_id": event["snapshot_id"], "source_id": event["source_id"],
        "content_sha256": event["content_sha256"], "cleaner_version": event["cleaner_version"],
        "clean_text": text,
    }
    assert hashlib.sha256(response.json()["clean_text"].encode("utf-8")).hexdigest() == event["content_sha256"]


def test_old_snapshot_unchanged_after_update_reversion_and_restart(collected):
    path, event, text = collected
    app = create_app(path)
    url = "/snapshots/" + event["snapshot_id"]
    with TestClient(app) as client:
        original = client.get(url).json()
        with closing(Collector(path)) as collector:
            collector.collect("S001", event["source_url"], lambda _: "<main><p>Different B</p></main>")
            collector.collect("S001", event["source_url"], lambda _: "<main><h1>Synthetic</h1><p>Café 학생 — original</p></main>")
            assert collector.pending_events()[-1]["source_version"] == 3
            assert collector.pending_events()[-1]["snapshot_id"] == event["snapshot_id"]
        assert client.get(url).json() == original
    with TestClient(create_app(path)) as client:
        assert client.get(url).json() == original


@pytest.mark.parametrize("snapshot_id", ["S001:" + "0" * 64, "S999:" + "a" * 64])
def test_missing_snapshot_is_404(collected, snapshot_id):
    with TestClient(create_app(collected[0])) as client:
        assert client.get("/snapshots/" + snapshot_id).status_code == 404


@pytest.mark.parametrize("snapshot_id", ["bad-id", "S001:" + "G" * 64, "S001:' OR 1=1--"])
def test_malformed_ids_are_rejected(collected, snapshot_id):
    with TestClient(create_app(collected[0])) as client:
        assert client.get("/snapshots/" + quote(snapshot_id, safe="")).status_code == 400


def test_readonly_connection_cannot_modify_collector(collected):
    with closing(open_readonly(collected[0])) as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM snapshots")


@pytest.mark.parametrize("existing_empty_db", [False, True])
def test_missing_or_wrong_database_fails_startup_without_creation(tmp_path, existing_empty_db):
    path = tmp_path / "wrong.sqlite3"
    if existing_empty_db:
        sqlite3.connect(path).close()
    with pytest.raises(RuntimeError, match="existing Collector database"):
        with TestClient(create_app(path)):
            pass
    assert path.exists() == existing_empty_db


def test_unavailable_database_returns_503_without_recreating(collected):
    path, event, _ = collected
    with TestClient(create_app(path)) as client:
        path.rename(path.with_suffix(".unavailable"))
        response = client.get("/snapshots/" + event["snapshot_id"])
        assert response.status_code == 503
        assert response.json() == {"detail": "Snapshot store unavailable"}
        assert not path.exists()


def test_corrupt_snapshot_is_not_served_as_success(collected):
    path, event, _ = collected
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE snapshots SET clean_text='damaged'")
    with TestClient(create_app(path)) as client:
        response = client.get("/snapshots/" + event["snapshot_id"])
        assert response.status_code == 500
        assert response.json() == {"detail": "Snapshot integrity check failed"}


def test_concurrent_reads_use_independent_connections(collected):
    path, event, _ = collected
    with TestClient(create_app(path)) as client:
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: client.get("/snapshots/" + event["snapshot_id"]), range(12)))
        assert all(response.status_code == 200 for response in responses)
        assert all(response.json() == responses[0].json() for response in responses)


def test_database_environment_setting(collected, monkeypatch):
    path, event, _ = collected
    monkeypatch.setenv("COLLECTOR_DB", str(path))
    with TestClient(create_app()) as client:
        assert client.get("/snapshots/" + event["snapshot_id"]).status_code == 200
