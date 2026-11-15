"""Demonstrate offline refresh and outbox replay with disposable local state."""
import argparse
from contextlib import closing
from functools import partial
from http.client import HTTPConnection
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
from threading import Thread
from uuid import uuid4

from source_collector.collector import Collector, MAX_HTML_BYTES, sha256
from source_collector.relay import Config, OutboxRelay, RabbitPublisher


FIXTURES = Path(__file__).resolve().parents[1] / "demo_pages" / "refresh"
SOURCE_ID = "SYN001"
# Canonical source identity only; the synthetic fetcher never contacts this URL.
SOURCE_URL = "https://www.irishimmigration.ie/synthetic-refresh-demo/"


class FixtureHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


def fixture_fetch(port, version):
    with closing(HTTPConnection("127.0.0.1", port, timeout=5)) as connection:
        connection.request("GET", f"/{version}.html")
        response = connection.getresponse()
        body = response.read(MAX_HTML_BYTES + 1)
        if response.status != 200 or len(body) > MAX_HTML_BYTES:
            raise RuntimeError("Local fixture unavailable or too large")
        return body.decode("utf-8")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def collect_sequence(db):
    steps = []
    handler = partial(FixtureHandler, directory=str(FIXTURES))
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
        thread.start()
        try:
            with closing(Collector(db)) as collector:
                for hour, version in enumerate(("a", "a", "b", "a")):
                    # The default live fetch path is never selected.
                    result = collector.collect(
                        SOURCE_ID, SOURCE_URL, lambda _: fixture_fetch(server.server_port, version),
                        at=f"2026-01-01T{hour:02d}:00:00Z",
                    )
                    status = collector.db.execute(
                        "SELECT detected_at, last_success_at FROM sources WHERE source_id=?", (SOURCE_ID,)
                    ).fetchone()
                    steps.append({"fixture": version.upper(), **result, **dict(status),
                                  "pending_events": len(collector.pending_events())})
                rows = collector.db.execute("SELECT snapshot_id,clean_text FROM snapshots").fetchall()
                require(len(rows) == 2, "Expected exactly two immutable snapshots")
                require(all(row["snapshot_id"] == f"{SOURCE_ID}:{sha256(row['clean_text'])}" for row in rows),
                        "Snapshot identity does not match stored text")
        finally:
            server.shutdown()
            thread.join()
    require([step["source_version"] for step in steps] == [1, 1, 2, 3], "Unexpected source versions")
    require([step["status"] for step in steps] == ["changed", "unchanged", "changed", "changed"],
            "Unexpected collection results")
    require([step["pending_events"] for step in steps] == [1, 1, 2, 3], "Unexpected outbox counts")
    require(steps[0]["snapshot_id"] == steps[1]["snapshot_id"] == steps[3]["snapshot_id"]
            != steps[2]["snapshot_id"], "Reversion should reuse the original snapshot")
    require(steps[0]["detected_at"] == steps[1]["detected_at"]
            and steps[0]["last_success_at"] < steps[1]["last_success_at"],
            "Unchanged refresh should advance freshness only")
    require(steps[1]["detected_at"] < steps[2]["detected_at"] < steps[3]["detected_at"],
            "Each changed version should advance detection time")
    return steps


def pending(db):
    with closing(Collector(db)) as collector:
        return collector.pending_events()


def replay(db, broker_url=None):
    expected = pending(db)
    require([e["event_id"] for e in expected] == [f"{SOURCE_ID}:{v}" for v in (1, 2, 3)],
            "Expected three durable pending events after reopening the store")
    if broker_url:
        # A bound, non-listening loopback port injects a real connection failure
        # without stopping or changing any shared RabbitMQ service.
        with closing(socket.socket()) as unavailable:
            unavailable.bind(("127.0.0.1", 0))
            port = unavailable.getsockname()[1]
            publisher = RabbitPublisher(Config(f"amqp://127.0.0.1:{port}/%2F", publish_timeout=2))
            with closing(OutboxRelay(db, publisher)) as relay:
                failure = relay.run_once()
    else:
        class Unavailable:
            def publish(self, body, event_id):
                raise TimeoutError("Synthetic broker outage")

        with closing(OutboxRelay(db, Unavailable())) as relay:
            failure = relay.run_once()
    require(failure["published"] == 0 and failure["failed"] == 1 and pending(db) == expected,
            "Failed publication should leave the complete outbox pending")

    delivered = []
    if broker_url:
        import pika

        queue = f"studentpath.refresh-demo.{uuid4().hex}"
        params = pika.URLParameters(broker_url)
        params.stack_timeout = 6
        params.socket_timeout = 5
        params.blocked_connection_timeout = 5
        with pika.BlockingConnection(params) as connection:
            channel = connection.channel()
            channel.queue_declare(queue=queue, durable=True)
            try:
                with closing(OutboxRelay(db, RabbitPublisher(Config(broker_url, queue, 5)))) as relay:
                    result = relay.run_once()
                for event in expected:
                    method, properties, body = channel.basic_get(queue)
                    require(method is not None and properties.message_id == event["event_id"]
                            and properties.delivery_mode == 2, "Missing or invalid persistent broker message")
                    delivered.append(json.loads(body))
                    channel.basic_ack(method.delivery_tag)
                require(channel.basic_get(queue)[0] is None, "Unexpected extra broker message")
            finally:
                channel.queue_delete(queue=queue)
    else:
        class RecordingPublisher:
            def publish(self, body, event_id):
                delivered.append(json.loads(body))

        with closing(OutboxRelay(db, RecordingPublisher())) as relay:
            result = relay.run_once()
    require(result == {"published": 3, "failed": 0} and not pending(db) and delivered == expected,
            "Recovery should publish the three original payloads and drain the outbox")
    return {"transport": "rabbitmq" if broker_url else "simulated",
            "failure": failure["error_type"], "published": result["published"],
            "event_ids": [event["event_id"] for event in delivered]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rabbitmq", action="store_true", help="Use RABBITMQ_INTEGRATION_URL for live replay")
    args = parser.parse_args()
    broker_url = os.environ.get("RABBITMQ_INTEGRATION_URL") if args.rabbitmq else None
    if args.rabbitmq and not broker_url:
        parser.error("--rabbitmq requires RABBITMQ_INTEGRATION_URL")
    with TemporaryDirectory(prefix="studentpath-refresh-") as work:
        db = Path(work) / "collector.sqlite3"
        print(json.dumps({"synthetic": True, "refresh": collect_sequence(db), "replay": replay(db, broker_url)},
                         indent=2))


if __name__ == "__main__":
    main()
