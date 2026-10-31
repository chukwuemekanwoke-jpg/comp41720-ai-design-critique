"""Local prototype AMQP consumer with confirmed quarantine publication."""
import json
import logging
import os
import time

import pika

from .index import SQLiteIndexBuilder
from .message_handler import MessageAction, RabbitMessageHandler
from .snapshot_client import CollectorSnapshotClient
from .store import IndexerStore
from .worker import IndexingWorker

log = logging.getLogger(__name__)


def deliver(channel, method, properties, body, handler, dead_queue):
    decision = handler.handle(body)
    if decision.action == MessageAction.REQUEUE:
        # Attempts are persisted by the worker and bounded (three by default).
        time.sleep(1)
        channel.basic_nack(method.delivery_tag, requeue=True)
    elif decision.action == MessageAction.DEAD_LETTER:
        # Publisher confirms are enabled before consuming. Never ACK the
        # original if quarantine publication fails; reconnect requeues it.
        channel.basic_publish(
            exchange='', routing_key=dead_queue, body=body, mandatory=True,
            properties=pika.BasicProperties(delivery_mode=2, content_type='application/json',
                                             message_id=properties.message_id),
        )
        channel.basic_ack(method.delivery_tag)
    else:
        channel.basic_ack(method.delivery_tag)
    print(json.dumps({'event_id': decision.event_id, 'action': decision.action.value}), flush=True)


def main():
    logging.basicConfig(level=logging.WARNING)
    url = os.environ['RABBITMQ_URL']
    queue = os.getenv('RABBITMQ_QUEUE', 'studentpath.local.updates')
    dead_queue = queue + '.deadletter'
    with IndexerStore(os.environ['INDEXER_DB']) as store:
        handler = RabbitMessageHandler(IndexingWorker(
            store, CollectorSnapshotClient(os.environ['COLLECTOR_BASE_URL']), SQLiteIndexBuilder(store)
        ))
        while True:
            connection = None
            try:
                params = pika.URLParameters(url)
                params.socket_timeout = 5
                params.stack_timeout = 10
                params.blocked_connection_timeout = 10
                connection = pika.BlockingConnection(params)
                channel = connection.channel()
                # Use a separate local queue; do not change the team's shared topology.
                channel.queue_declare(queue=queue, durable=True)
                channel.queue_declare(queue=dead_queue, durable=True)
                channel.confirm_delivery()
                channel.basic_qos(prefetch_count=1)
                channel.basic_consume(queue=queue, auto_ack=False,
                    on_message_callback=lambda ch, method, props, body:
                        deliver(ch, method, props, body, handler, dead_queue))
                channel.start_consuming()
            except KeyboardInterrupt:
                return
            except Exception as error:
                log.warning('Consumer reconnecting after %s', type(error).__name__)
                time.sleep(2)
            finally:
                if connection is not None and connection.is_open:
                    try:
                        connection.close()
                    except Exception:
                        pass


if __name__ == '__main__':
    main()
