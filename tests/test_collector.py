from pathlib import Path
import json
import sqlite3

import pytest

from source_collector.collector import Collector, check_official_url, clean_main_text, collect_manifest

URL = "https://www.irishimmigration.ie/official-test/"
HTML_A = "<html><body><header>Menu</header><main><h1>Stamp 1G</h1><p>Graduate permission.</p><table><tr><th>Type</th><th>Status</th></tr><tr><td>Stamp 1G</td><td>Permitted</td></tr></table></main><footer>Contact</footer></body></html>"
HTML_B = HTML_A.replace("Graduate permission.", "Graduate permission updated.")


def test_extracts_main_content_and_table_rows():
    text = clean_main_text(HTML_A)
    assert "Stamp 1G\nGraduate permission." in text
    assert "Type | Status" in text
    assert "Stamp 1G | Permitted" in text
    assert "Menu" not in text and "Contact" not in text


def test_snapshots_change_outbox_and_unchanged(tmp_path):
    c = Collector(tmp_path / "collector.sqlite3")
    try:
        first = c.collect("S001", URL, lambda _: HTML_A, at="2026-10-23T10:00:00Z")
        same = c.collect("S001", URL, lambda _: HTML_A.replace("<header>Menu</header>", "<header>Other navigation</header>"), at="2026-10-23T11:00:00Z")
        second = c.collect("S001", URL, lambda _: HTML_B, at="2026-10-23T12:00:00Z")
        assert [first["status"], same["status"], second["status"]] == ["changed", "unchanged", "changed"]
        assert [first["source_version"], same["source_version"], second["source_version"]] == [1, 1, 2]
        assert len(c.pending_events()) == 2
        assert c.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 2
        s = c.db.execute("SELECT * FROM sources WHERE source_id='S001'").fetchone()
        assert s["last_attempt_at"] == s["last_success_at"] == "2026-10-23T12:00:00Z"
    finally:
        c.close()


def test_fetch_failure_does_not_replace_last_good_check(tmp_path):
    c = Collector(tmp_path / "collector.sqlite3")
    try:
        c.collect("S001", URL, lambda _: HTML_A, at="2026-10-23T10:00:00Z")
        def unavailable(_):
            raise ConnectionError("simulated outage")
        result = c.collect("S001", URL, unavailable, at="2026-10-23T13:00:00Z")
        assert result["status"] == "fetch_failed"
        state = c.db.execute("SELECT * FROM sources WHERE source_id='S001'").fetchone()
        assert state["last_attempt_at"] == "2026-10-23T13:00:00Z"
        assert state["last_success_at"] == "2026-10-23T10:00:00Z"
        assert len(c.pending_events()) == 1
    finally:
        c.close()


def test_restart_keeps_unpublished_outbox(tmp_path):
    db = tmp_path / "collector.sqlite3"
    first = Collector(db)
    first.collect("S001", URL, lambda _: HTML_A)
    first.close()
    second = Collector(db)
    try:
        assert [e["event_id"] for e in second.pending_events()] == ["S001:1"]
        result = second.collect("S001", URL, lambda _: HTML_B)
        assert result["source_version"] == 2
    finally:
        second.close()


def test_reversion_increases_version_and_reuses_snapshot(tmp_path):
    c = Collector(tmp_path / "collector.sqlite3")
    try:
        for html in (HTML_A, HTML_B, HTML_A):
            result = c.collect("S001", URL, lambda _, html=html: html)
        assert result["source_version"] == 3
        assert c.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 2
        assert [e["source_version"] for e in c.pending_events()] == [1, 2, 3]
    finally:
        c.close()


def test_official_url_validation():
    for url in ("http://www.irishimmigration.ie/a", "https://other.ie/a", "https://www.irishimmigration.ie.evil.test/a", "https://user@www.irishimmigration.ie/a"):
        with pytest.raises(ValueError):
            check_official_url(url)


def test_manifest_offline_fixture(tmp_path):
    directory = tmp_path / "fixtures"
    directory.mkdir()
    (directory / "S001.html").write_text(HTML_A, encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"sources": [{"source_id": "S001", "canonical_url": URL}]}))
    result = collect_manifest(tmp_path / "collector.sqlite3", manifest, directory)
    assert result[0]["status"] == "changed"


def test_concurrent_registration_cannot_mix_source_urls(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    path = tmp_path / "collector.sqlite3"
    Collector(path).close()
    ready = Barrier(2)

    def register(url):
        c = Collector(path)
        ready.wait(timeout=5)
        try:
            c.collect("S001", url, lambda _: HTML_A)
            return url
        except ValueError:
            return None
        finally:
            c.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(register, [URL, URL + "different/"]))
    winner = [result for result in results if result]
    assert len(winner) == 1
    c = Collector(path)
    try:
        assert c.db.execute("SELECT url FROM sources").fetchone()[0] == winner[0]
        assert [event["source_url"] for event in c.pending_events()] == winner
    finally:
        c.close()


def test_outbox_insert_failure_rolls_back_snapshot_and_version(tmp_path):
    c = Collector(tmp_path / "collector.sqlite3")
    try:
        c.collect("S001", URL, lambda _: HTML_A)
        c.db.execute("""CREATE TRIGGER fail_outbox BEFORE INSERT ON outbox
                        BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
        with pytest.raises(sqlite3.IntegrityError):
            c.collect("S001", URL, lambda _: HTML_B)
        assert c.db.execute("SELECT source_version FROM sources").fetchone()[0] == 1
        assert c.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1
        assert len(c.pending_events()) == 1
    finally:
        c.close()
