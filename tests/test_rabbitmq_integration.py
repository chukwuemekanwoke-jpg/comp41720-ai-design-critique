"""Opt-in test against a local broker; never runs without explicit configuration."""
import os
import uuid

import pytest

from source_collector.collector import Collector
from source_collector.relay import Config, OutboxRelay, RabbitPublisher


@pytest.mark.skipif(not os.environ.get("RABBITMQ_INTEGRATION_URL"),
                    reason="Set RABBITMQ_INTEGRATION_URL to run against a local broker")
def test_real_broker_confirm_and_consume(tmp_path):
    import pika
    url = os.environ["RABBITMQ_INTEGRATION_URL"]
    queue = "studentpath.integration." + uuid.uuid4().hex
    db = tmp_path / "collector.sqlite3"
    collector = Collector(db)
    collector.collect("S001", "https://www.irishimmigration.ie/test/",
                      lambda _: "<main><p>Synthetic test</p></main>")
    expected = collector.pending_events()[0]
    collector.close()
    connection = pika.BlockingConnection(pika.URLParameters(url))
    relay = OutboxRelay(db, RabbitPublisher(Config(url, queue)))
    try:
        assert relay.run_once()["published"] == 1
        channel = connection.channel()
        method, properties, body = channel.basic_get(queue=queue, auto_ack=False)
        import json
        assert json.loads(body) == expected
        assert properties.delivery_mode == 2
        assert properties.message_id == expected["event_id"]
        channel.basic_ack(method.delivery_tag)
        assert channel.basic_get(queue=queue)[0] is None
    finally:
        connection.channel().queue_delete(queue=queue)
        connection.close()
        relay.close()
