"""Confirmed changes, freshness and read-only handoff must stay distinguishable."""
from contextlib import closing
from datetime import datetime, timezone
import json
import sqlite3
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from source_collector.collector import Collector, SCHEMA, sha256
from source_collector.snapshot_api import create_app


URL = "https://www.irishimmigration.ie/synthetic-test/"
A = "<main><h1>Synthetic A</h1><p>Not official guidance.</p></main>"
B = A.replace("Synthetic A", "Synthetic B")
T1, T2, T3, T4, T5 = [f"2026-11-04T0{hour}:00:00+00:00" for hour in range(1, 6)]


def fail(_):
    raise ConnectionError("https://private-user:secret@example.invalid/?token=private-token")


def collect(collector, html, at):
    return collector.collect("S001", URL, lambda _: html, at=at)


def state(collector):
    return dict(collector.db.execute("SELECT * FROM sources WHERE source_id='S001'").fetchone())


def status(client):
    response = client.get("/sources/S001/status")
    assert response.status_code == 200, response.text
    return response.json()


def test_initial_unchanged_changed_and_reversion_are_atomic_and_persistent(tmp_path):
    path = tmp_path / "collector.sqlite3"
    with closing(Collector(path)) as collector:
        first = collect(collector, A, T1)
        with TestClient(create_app(path)) as client:
            original_snapshot = client.get("/snapshots/" + first["snapshot_id"]).json()
            assert status(client) == {
                "source_id": "S001", "source_version": 1, "snapshot_id": first["snapshot_id"],
                "detected_at": T1, "last_success_at": T1, "last_attempt_at": T1, "last_error": None,
            }
            collect(collector, A, T2)
            unchanged = status(client)
            assert unchanged["detected_at"] == T1
            assert unchanged["snapshot_id"] == first["snapshot_id"]
            assert unchanged["source_version"] == 1
            assert unchanged["last_success_at"] == unchanged["last_attempt_at"] == T2
            assert len(collector.pending_events()) == 1
            assert collector.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1
            second = collect(collector, B, T3)
            assert status(client)["detected_at"] == T3
            assert status(client)["source_version"] == 2
            assert status(client)["snapshot_id"] == second["snapshot_id"] != first["snapshot_id"]
            third = collect(collector, A, T4)
            assert status(client)["detected_at"] == T4
            assert status(client)["source_version"] == 3
            assert third["snapshot_id"] == first["snapshot_id"]
            assert collector.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 2
            assert client.get("/snapshots/" + first["snapshot_id"]).json() == original_snapshot
            events = collector.pending_events()
            assert [e["source_version"] for e in events] == [1, 2, 3]
            assert [e["checked_at"] for e in events] == [T1, T3, T4]
            assert all(set(e) == {"event_id", "source_id", "source_version", "snapshot_id",
                                  "content_sha256", "source_url", "checked_at", "cleaner_version"} for e in events)
    with closing(Collector(path)) as collector, TestClient(create_app(path)) as client:
        assert status(client)["detected_at"] == T4
        assert status(client)["source_version"] == 3
        assert len(collector.pending_events()) == 3


def test_failure_and_recovery_never_invent_a_change_or_leak_error_details(tmp_path):
    path = tmp_path / "collector.sqlite3"
    with closing(Collector(path)) as collector, TestClient(create_app(path)) as client:
        first = collect(collector, A, T1)
        collector.collect("S001", URL, fail, at=T2)
        failed = status(client)
        assert failed["source_version"] == 1
        assert failed["snapshot_id"] == first["snapshot_id"]
        assert failed["detected_at"] == failed["last_success_at"] == T1
        assert failed["last_attempt_at"] == T2
        assert failed["last_error"]
        assert not any(secret in json.dumps(failed) for secret in ("private-user", "secret", "private-token"))
        collect(collector, A, T3)
        recovered = status(client)
        assert recovered["last_error"] is None
        assert recovered["last_success_at"] == recovered["last_attempt_at"] == T3
        assert recovered["detected_at"] == T1 and recovered["source_version"] == 1
        assert len(collector.pending_events()) == 1


def test_first_failed_fetch_exposes_unconfirmed_zero_version(tmp_path):
    path = tmp_path / "collector.sqlite3"
    with closing(Collector(path)) as collector, TestClient(create_app(path)) as client:
        collector.collect("S001", URL, fail, at=T1)
        payload = status(client)
        assert payload["source_version"] == 0
        assert payload["snapshot_id"] is payload["detected_at"] is payload["last_success_at"] is None
        assert payload["last_attempt_at"] == T1 and payload["last_error"]
        assert collector.pending_events() == []
        collect(collector, A, T2)
        assert status(client)["source_version"] == 1
        assert status(client)["detected_at"] == T2
        assert status(client)["last_error"] is None


def test_detection_timestamp_rolls_back_with_snapshot_event_and_version(tmp_path):
    with closing(Collector(tmp_path / "collector.sqlite3")) as collector:
        collect(collector, A, T1)
        before = state(collector)
        collector.db.execute("""CREATE TRIGGER reject_outbox BEFORE INSERT ON outbox
            BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
        with pytest.raises(sqlite3.IntegrityError):
            collect(collector, B, T2)
        after = state(collector)
        for field in ("detected_at", "source_version", "latest_snapshot_id", "latest_hash", "last_success_at"):
            assert after[field] == before[field]
        assert after["last_attempt_at"] == T2
        assert len(collector.pending_events()) == 1
        assert collector.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1


def test_detection_is_recorded_after_fetch_not_at_attempt_start(tmp_path, monkeypatch):
    timestamps = iter([T1, T2])
    monkeypatch.setattr("source_collector.collector.utc_now", lambda: next(timestamps))
    with closing(Collector(tmp_path / "collector.sqlite3")) as collector:
        collector.collect("S001", URL, lambda _: A)
        saved = state(collector)
        assert saved["last_attempt_at"] == T1
        assert saved["detected_at"] == saved["last_success_at"] == T2
        assert collector.pending_events()[0]["checked_at"] == T2


@pytest.mark.parametrize("at", ["2026-11-04T01:00:00", "2026-11-04", "", "not-a-date"])
def test_naive_or_invalid_timestamp_does_not_register_source(tmp_path, at):
    with closing(Collector(tmp_path / "collector.sqlite3")) as collector:
        with pytest.raises(ValueError):
            collect(collector, A, at)
        assert collector.db.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0


def legacy_database(path):
    """Literal pre-status sources schema, with original snapshot/outbox tables."""
    db = sqlite3.connect(path)
    db.executescript("""CREATE TABLE sources (
        source_id TEXT PRIMARY KEY, url TEXT NOT NULL,
        last_attempt_at TEXT, last_success_at TEXT, last_error TEXT,
        latest_hash TEXT, latest_snapshot_id TEXT, source_version INTEGER NOT NULL DEFAULT 0
    );""")
    db.executescript(SCHEMA)  # CREATE IF NOT EXISTS must preserve the legacy sources table.
    digest = sha256("Synthetic historical A")
    snapshot_id = "S001:" + digest
    db.execute("""INSERT INTO sources(source_id,url,last_attempt_at,last_success_at,
        latest_hash,latest_snapshot_id,source_version) VALUES (?,?,?,?,?,?,3)""",
               ("S001", URL, T5, T5, digest, snapshot_id))
    db.execute("INSERT INTO snapshots VALUES (?,?,?,?,?,?,?)",
               (snapshot_id, "S001", digest, "main-text-v1", A, "Synthetic historical A", T1))
    event = dict(event_id="S001:3", source_id="S001", source_version=3, snapshot_id=snapshot_id,
                 content_sha256=digest, source_url=URL, checked_at=T3, cleaner_version="main-text-v1")
    db.execute("""INSERT INTO outbox(event_id,source_id,source_version,payload_json,created_at,status)
        VALUES ('S001:3','S001',3,?,?,'published')""", (json.dumps(event), T3))
    db.commit()
    return db, event


def test_legacy_backfill_uses_latest_logical_event_not_recheck_or_first_snapshot(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    db, event = legacy_database(path)
    db.close()
    for _ in range(2):
        with closing(Collector(path)) as collector, TestClient(create_app(path)) as client:
            payload = status(client)
            assert payload["detected_at"] == T3  # Neither first snapshot T1 nor unchanged recheck T5.
            assert payload["last_success_at"] == T5
            assert payload["snapshot_id"] == event["snapshot_id"]
            assert collector.db.execute("SELECT payload_json FROM outbox").fetchone()[0] == json.dumps(event)
            assert client.get("/snapshots/" + event["snapshot_id"]).status_code == 200


@pytest.mark.parametrize("history", ["missing", "invalid-json", "wrong-version", "wrong-snapshot", "naive-time"])
def test_unverifiable_legacy_detection_stays_null(tmp_path, history):
    path = tmp_path / "legacy.sqlite3"
    db, event = legacy_database(path)
    if history == "missing":
        db.execute("DELETE FROM outbox")
    else:
        if history == "wrong-version":
            event["source_version"] = 2
        elif history == "wrong-snapshot":
            event["snapshot_id"] = "S001:" + "0" * 64
        elif history == "naive-time":
            event["checked_at"] = "2026-11-04T03:00:00"
        db.execute("UPDATE outbox SET payload_json=?", ("{" if history == "invalid-json" else json.dumps(event),))
    db.commit()
    db.close()
    with closing(Collector(path)), TestClient(create_app(path)) as client:
        assert status(client)["detected_at"] is None
        assert status(client)["source_version"] == 3


def test_legacy_api_never_migrates_and_snapshots_stay_usable(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    db, event = legacy_database(path)
    db.close()
    with TestClient(create_app(path)) as client:
        assert client.get("/snapshots/" + event["snapshot_id"]).status_code == 200
        assert client.get("/sources/S001/status").status_code == 503
    with closing(sqlite3.connect(path)) as db:
        assert "detected_at" not in {row[1] for row in db.execute("PRAGMA table_info(sources)")}


def test_status_reads_do_not_mutate_store_fetch_or_publish(tmp_path, monkeypatch):
    path = tmp_path / "collector.sqlite3"
    with closing(Collector(path)) as collector:
        collect(collector, A, T1)
        before = "\n".join(collector.db.iterdump())
    def forbidden(*args, **kwargs):
        raise AssertionError("Status requests must not fetch or publish")
    monkeypatch.setattr("source_collector.collector.fetch_official_html", forbidden)
    monkeypatch.setattr("source_collector.relay.RabbitPublisher.publish", forbidden)
    with TestClient(create_app(path)) as client:
        for _ in range(3):
            assert status(client)["detected_at"] == T1
    with closing(sqlite3.connect(path)) as db:
        assert "\n".join(db.iterdump()) == before


@pytest.mark.parametrize("source_id,code", [("unknown", 404), ("bad:id", 400), ("bad id", 400), ("x" * 51, 400)])
def test_unknown_or_invalid_source_id(tmp_path, source_id, code):
    path = tmp_path / "collector.sqlite3"
    Collector(path).close()
    with TestClient(create_app(path)) as client:
        assert client.get(f"/sources/{source_id}/status").status_code == code


@pytest.mark.parametrize("corruption", ["snapshot", "version", "timestamp", "missing-snapshot"])
def test_inconsistent_confirmed_status_fails_closed(tmp_path, corruption):
    path = tmp_path / "collector.sqlite3"
    with closing(Collector(path)) as collector:
        collect(collector, A, T1)
        if corruption == "snapshot":
            sql = "UPDATE sources SET latest_snapshot_id='S001:invalid'"
        elif corruption == "version":
            sql = "UPDATE sources SET source_version=0"
        elif corruption == "timestamp":
            sql = "UPDATE sources SET detected_at='2026-11-04T03:00:00'"
        else:
            sql = "DELETE FROM snapshots"
        with collector.db:
            collector.db.execute(sql)
    with TestClient(create_app(path)) as client:
        assert client.get("/sources/S001/status").status_code == 500


def test_status_unavailable_store_returns_503_without_creating_db(tmp_path):
    path = tmp_path / "collector.sqlite3"
    Collector(path).close()
    with TestClient(create_app(path)) as client:
        path.rename(path.with_suffix(".offline"))
        response = client.get("/sources/S001/status")
        assert response.status_code == 503
        assert response.json() == {"detail": "Source status store unavailable"}
        assert not path.exists()


def test_offset_timestamp_is_returned_in_utc(tmp_path):
    path = tmp_path / "collector.sqlite3"
    with closing(Collector(path)) as collector:
        collect(collector, A, "2026-11-04T03:00:00+02:00")
    with TestClient(create_app(path)) as client:
        payload = status(client)
        for field in ("detected_at", "last_success_at", "last_attempt_at"):
            assert payload[field] == T1
            assert datetime.fromisoformat(payload[field]).utcoffset() == timezone.utc.utcoffset(None)


def test_migration_command_is_repeatable_and_does_not_fetch_or_publish(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    db, event = legacy_database(path)
    before = {table: db.execute(f"SELECT * FROM {table}").fetchall() for table in ("snapshots", "outbox")}
    db.close()
    for _ in range(2):
        result = subprocess.run([sys.executable, "-m", "source_collector.migrate", "--db", str(path)],
                                capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT detected_at FROM sources").fetchone()[0] == T3
        assert {table: db.execute(f"SELECT * FROM {table}").fetchall() for table in before} == before


def test_migration_command_rejects_missing_database_without_creation(tmp_path):
    path = tmp_path / "missing.sqlite3"
    result = subprocess.run([sys.executable, "-m", "source_collector.migrate", "--db", str(path)],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode != 0
    assert not path.exists()


def test_concurrent_writer_startups_migrate_a_legacy_database_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    path = tmp_path / "legacy.sqlite3"
    db, _ = legacy_database(path)
    db.close()
    ready = Barrier(2)

    def start(_):
        ready.wait(timeout=5)
        with closing(Collector(path)) as collector:
            return state(collector)["detected_at"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(start, range(2))) == [T3, T3]


def test_outbox_publication_failure_does_not_change_confirmed_status(tmp_path):
    from source_collector.relay import OutboxRelay
    from unittest.mock import Mock
    path = tmp_path / "collector.sqlite3"
    with closing(Collector(path)) as collector:
        collect(collector, A, T1)
    with TestClient(create_app(path)) as client:
        before = status(client)
        with closing(OutboxRelay(path, Mock(publish=Mock(side_effect=ConnectionError("outage"))))) as relay:
            assert relay.run_once()["failed"] == 1
        assert status(client) == before


def test_unknown_legacy_detection_is_not_invented_by_unchanged_check(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    db, _ = legacy_database(path)
    db.execute("DELETE FROM outbox")
    db.commit()
    db.close()
    with closing(Collector(path)) as collector:
        collect(collector, "<main><p>Synthetic historical A</p></main>", T5)
        assert state(collector)["detected_at"] is None
        assert state(collector)["source_version"] == 3
        assert collector.pending_events() == []
