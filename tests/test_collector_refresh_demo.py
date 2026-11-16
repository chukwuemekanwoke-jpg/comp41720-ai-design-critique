from scripts.demo_collector_refresh import collect_sequence, replay


def test_offline_refresh_and_outbox_replay(tmp_path, monkeypatch):
    def unexpected_live_fetch(*args, **kwargs):
        raise AssertionError("The offline demo must not use the live HTTP opener")

    monkeypatch.setattr("source_collector.collector.build_opener", unexpected_live_fetch)
    db = tmp_path / "demo.sqlite3"
    steps = collect_sequence(db)
    assert [step["fixture"] for step in steps] == ["A", "A", "B", "A"]
    assert replay(db) == {
        "transport": "simulated",
        "failure": "TimeoutError",
        "published": 3,
        "event_ids": ["SYN001:1", "SYN001:2", "SYN001:3"],
    }
