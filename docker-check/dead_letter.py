"""Dead-letter inspection for the product check that leaves other messages alone."""


def take_quarantined(channel, queue, marker):
    """Remove only this check's marker from the dead-letter queue.

    Other dead letters belong to the running pipeline or earlier runs, so they
    are held unacknowledged while searching and then requeued, never consumed.
    """
    held = []
    try:
        while True:
            method, _properties, body = channel.basic_get(queue=queue, auto_ack=False)
            if method is None:
                return False
            if body == marker:
                channel.basic_ack(method.delivery_tag)
                return True
            held.append(method.delivery_tag)
    finally:
        for tag in held:
            channel.basic_nack(tag, requeue=True)
