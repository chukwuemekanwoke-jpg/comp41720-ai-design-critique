"""Restart-safe, at-least-once delivery of the collector's SQLite outbox."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from dataclasses import dataclass

from .collector import utc_now


@dataclass(frozen=True)
class Config:
    url: str
    queue: str = "studentpath.document-updates"
    publish_timeout: float = 15

    @classmethod
    def from_env(cls):
        url = os.environ.get("RABBITMQ_URL", "")
        queue = os.environ.get("RABBITMQ_QUEUE", cls.queue)
        timeout = float(os.environ.get("RELAY_PUBLISH_TIMEOUT", "15"))
        if not url.startswith(("amqp://", "amqps://")) or not queue or timeout <= 0:
            raise ValueError("Set RABBITMQ_URL, a nonempty RABBITMQ_QUEUE and positive RELAY_PUBLISH_TIMEOUT")
        return cls(url, queue, timeout)


class RabbitPublisher:
    def __init__(self, config: Config):
        self.config = config

    def publish(self, payload_json: str, event_id: str) -> None:
        # Lazy import keeps offline collection independent of the broker client.
        import pika

        params = pika.URLParameters(self.config.url)
        params.connection_attempts = 1
        params.socket_timeout = self.config.publish_timeout
        params.stack_timeout = self.config.publish_timeout + 1
        params.blocked_connection_timeout = self.config.publish_timeout
        params.heartbeat = 30
        connection = pika.BlockingConnection(params)

        def timed_out():
            raise TimeoutError("Broker confirmation deadline exceeded")

        timer = connection.call_later(self.config.publish_timeout, timed_out)
        try:
            channel = connection.channel()
            channel.queue_declare(queue=self.config.queue, durable=True)
            channel.confirm_delivery()
            channel.basic_publish(
                exchange="", routing_key=self.config.queue,
                body=payload_json.encode("utf-8"), mandatory=True,
                properties=pika.BasicProperties(
                    delivery_mode=2, content_type="application/json",
                    content_encoding="utf-8", message_id=event_id,
                    type="document.updated"),
            )
        finally:
            connection.remove_timeout(timer)
            if connection.is_open:
                try:
                    connection.close()
                except Exception:
                    pass  # A close failure does not undo an acknowledged publish.


class OutboxRelay:
    def __init__(self, db_path, publisher, *, lock_timeout=10):
        # Require an existing collector database: never silently create the wrong DB.
        from pathlib import Path
        self.db = sqlite3.connect(
            Path(db_path).resolve().as_uri() + "?mode=rw", uri=True,
            timeout=lock_timeout,
        )
        self.db.row_factory = sqlite3.Row
        self.publisher = publisher

    def close(self):
        self.db.close()

    def run_once(self, limit=100):
        if limit <= 0:
            raise ValueError("limit must be positive")
        published = 0
        for _ in range(limit):
            with self.db:
                # Hold the write reservation until confirmation and status commit.
                # A crash releases it and rolls back; another relay may then retry.
                self.db.execute("BEGIN IMMEDIATE")
                row = self.db.execute("""SELECT event_id,payload_json FROM outbox
                    WHERE status='pending' ORDER BY created_at,source_id,source_version
                    LIMIT 1""").fetchone()
                if row is None:
                    break
                self.db.execute("UPDATE outbox SET attempts=attempts+1 WHERE event_id=?", (row["event_id"],))
                try:
                    self.publisher.publish(row["payload_json"], row["event_id"])
                except Exception as exc:
                    # Do not log exception text: broker errors may contain credentials.
                    return {"published": published, "failed": 1, "error_type": type(exc).__name__}
                self.db.execute("""UPDATE outbox SET status='published',published_at=?
                    WHERE event_id=?""", (utc_now(), row["event_id"]))
            published += 1
        return {"published": published, "failed": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("COLLECTOR_DB", "collector.sqlite3"))
    parser.add_argument("--once", action="store_true", help="Drain one batch and exit")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    try:
        config = Config.from_env()
        interval = float(os.environ.get("RELAY_RETRY_SECONDS", "5"))
        if interval <= 0 or args.limit <= 0:
            raise ValueError("Retry interval and batch limit must be positive")
        relay = OutboxRelay(args.db, RabbitPublisher(config))
    except Exception as exc:
        print(json.dumps({"error_type": type(exc).__name__, "status": "configuration_failed"}))
        return 2
    try:
        while True:
            try:
                result = relay.run_once(args.limit)
            except sqlite3.Error as exc:
                result = {"published": 0, "failed": 1, "error_type": type(exc).__name__}
            print(json.dumps(result), flush=True)
            if args.once:
                return 1 if result["failed"] else 0
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0
    finally:
        relay.close()


if __name__ == "__main__":
    raise SystemExit(main())
