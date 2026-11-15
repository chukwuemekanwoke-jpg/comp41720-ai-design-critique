import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Event
from unittest.mock import Mock

import pytest

from source_collector.collector import Collector
from source_collector.relay import Config, OutboxRelay, RabbitPublisher


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "collector.sqlite3"
    collector = Collector(path)
    collector.collect("S001", "https://www.irishimmigration.ie/test/",
                      lambda _: "<main><p>Original</p></main>")
    collector.collect("S001", "https://www.irishimmigration.ie/test/",
                      lambda _: "<main><p>Updated</p></main>")
    collector.close()
    return path


def test_confirmed_publish_preserves_payload_and_marks_sent(database):
    publisher = Mock()
    relay = OutboxRelay(database, publisher)
    expected = relay.db.execute("SELECT payload_json FROM outbox ORDER BY source_version").fetchall()
    try:
        assert relay.run_once() == {"published": 2, "failed": 0}
        assert [c.args[0] for c in publisher.publish.call_args_list] == [r[0] for r in expected]
        assert [c.args[1] for c in publisher.publish.call_args_list] == ["S001:1", "S001:2"]
        assert all(r[0] == "published" and r[1] and r[2] == 1 for r in
                   relay.db.execute("SELECT status,published_at,attempts FROM outbox"))
        assert relay.run_once()["published"] == 0
    finally:
        relay.close()


@pytest.mark.parametrize("error", [ConnectionError, TimeoutError])
def test_failure_then_restart_retries_pending(database, error):
    publisher = Mock()
    publisher.publish.side_effect = error("outage")
    first = OutboxRelay(database, publisher)
    assert first.run_once()["failed"] == 1
    assert tuple(first.db.execute("SELECT status,published_at,attempts FROM outbox WHERE event_id='S001:1'").fetchone()) == ("pending", None, 1)
    first.close()
    publisher.publish.side_effect = None
    second = OutboxRelay(database, publisher)
    try:
        assert second.run_once()["published"] == 2
        assert second.db.execute("SELECT attempts FROM outbox WHERE event_id='S001:1'").fetchone()[0] == 2
    finally:
        second.close()


def test_crash_after_broker_confirmation_causes_safe_duplicate(database):
    class Crash(BaseException):
        pass

    received = []

    def crash_after_receipt(body, event_id):
        received.append(event_id)
        raise Crash()

    publisher = Mock()
    publisher.publish.side_effect = crash_after_receipt
    first = OutboxRelay(database, publisher)
    with pytest.raises(Crash):
        first.run_once()
    first.close()
    publisher.publish.side_effect = lambda body, event_id: received.append(event_id)
    second = OutboxRelay(database, publisher)
    try:
        second.run_once()
        assert received == ["S001:1", "S001:1", "S001:2"]
    finally:
        second.close()


def test_database_mark_failure_keeps_event_pending(database):
    publisher = Mock()
    relay = OutboxRelay(database, publisher)
    relay.db.execute("""CREATE TRIGGER fail_mark BEFORE UPDATE OF status ON outbox
                     BEGIN SELECT RAISE(ABORT, 'injected disk failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        relay.run_once()
    assert relay.db.execute("SELECT status FROM outbox LIMIT 1").fetchone()[0] == "pending"
    relay.db.execute("DROP TRIGGER fail_mark")
    assert relay.run_once()["published"] == 2
    assert [call.args[1] for call in publisher.publish.call_args_list] == ["S001:1", "S001:1", "S001:2"]
    relay.close()


def test_concurrent_relay_cannot_claim_in_flight_event(database):
    second_publisher = Mock()
    second = OutboxRelay(database, second_publisher, lock_timeout=0.01)

    def publish(body, event_id):
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            second.run_once()

    first = OutboxRelay(database, Mock(publish=publish))
    try:
        assert first.run_once()["published"] == 2
        assert second.run_once()["published"] == 0
        second_publisher.publish.assert_not_called()
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize("broker_error", [None, TimeoutError])
def test_collector_can_commit_while_relay_waits_for_broker(database, broker_error):
    publishing = Event()
    release = Event()

    def publish(body, event_id):
        publishing.set()
        if not release.wait(5):
            raise RuntimeError("Test did not release publisher")
        if broker_error:
            raise broker_error("simulated confirmation timeout")

    def run_relay():
        with closing(OutboxRelay(database, Mock(publish=publish))) as relay:
            return relay.run_once(limit=1)

    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(run_relay)
        try:
            assert publishing.wait(5)
            # Fail fast if the relay reserves the actual Collector database.
            with closing(sqlite3.connect(database, timeout=0)) as probe:
                probe.execute("BEGIN IMMEDIATE")
                probe.rollback()
            with closing(Collector(database)) as collector:
                collector.db.execute("PRAGMA busy_timeout=0")
                outcome = collector.collect("S001", "https://www.irishimmigration.ie/test/",
                                            lambda _: "<main><p>Third version</p></main>")
                assert outcome["source_version"] == 3
                assert {e["event_id"] for e in collector.pending_events()} == {
                    "S001:1", "S001:2", "S001:3",
                }
        finally:
            release.set()
        assert result.result(timeout=5)["failed"] == int(broker_error is not None)

    publisher = Mock()
    with closing(OutboxRelay(database, publisher, lock_timeout=0)) as relay:
        expected = ["S001:2", "S001:3"]
        if broker_error:
            expected.insert(0, "S001:1")
        assert relay.run_once() == {"published": len(expected), "failed": 0}
        assert [call.args[1] for call in publisher.publish.call_args_list] == expected
        assert relay.db.execute("SELECT COUNT(*) FROM outbox WHERE status='published'").fetchone()[0] == 3


def test_rabbit_adapter_uses_confirms_persistence_and_mandatory(monkeypatch):
    import pika
    connection = Mock()
    monkeypatch.setattr(pika, "BlockingConnection", Mock(return_value=connection))
    publisher = RabbitPublisher(Config("amqp://example:secret@localhost:5672/%2F"))
    publisher.publish('{"event_id":"S001:1"}', "S001:1")
    channel = connection.channel.return_value
    channel.queue_declare.assert_called_once_with(queue="studentpath.document-updates", durable=True)
    channel.confirm_delivery.assert_called_once()
    kwargs = channel.basic_publish.call_args.kwargs
    assert kwargs["mandatory"] is True
    assert kwargs["properties"].delivery_mode == 2
    assert kwargs["properties"].message_id == "S001:1"
    assert json.loads(kwargs["body"])["event_id"] == "S001:1"
    calls = [call[0] for call in channel.method_calls]
    assert calls == ["queue_declare", "confirm_delivery", "basic_publish"]


@pytest.mark.parametrize("failure", ["nack", "unroutable"])
def test_broker_rejection_remains_pending(database, monkeypatch, failure):
    import pika
    connection = Mock()
    error = pika.exceptions.NackError if failure == "nack" else pika.exceptions.UnroutableError
    connection.channel.return_value.basic_publish.side_effect = error([])
    monkeypatch.setattr(pika, "BlockingConnection", Mock(return_value=connection))
    relay = OutboxRelay(database, RabbitPublisher(Config("amqp://user:pass@localhost/%2F")))
    try:
        assert relay.run_once()["failed"] == 1
        assert relay.db.execute("SELECT COUNT(*) FROM outbox WHERE status='pending'").fetchone()[0] == 2
    finally:
        relay.close()


def test_config_requires_external_credentials(monkeypatch):
    monkeypatch.delenv("RABBITMQ_URL", raising=False)
    with pytest.raises(ValueError):
        Config.from_env()


def test_confirmation_deadline_keeps_event_pending(database, monkeypatch):
    import pika
    connection = Mock()
    monkeypatch.setattr(pika, "BlockingConnection", Mock(return_value=connection))
    def expire(**kwargs):
        connection.call_later.call_args.args[1]()
    connection.channel.return_value.basic_publish.side_effect = expire
    relay = OutboxRelay(database, RabbitPublisher(Config("amqp://user:pass@localhost/%2F")))
    try:
        assert relay.run_once()["error_type"] == "TimeoutError"
        assert relay.db.execute("SELECT COUNT(*) FROM outbox WHERE status='pending'").fetchone()[0] == 2
    finally:
        relay.close()


def test_missing_database_is_not_created(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        OutboxRelay(path, Mock())
    assert not path.exists()
