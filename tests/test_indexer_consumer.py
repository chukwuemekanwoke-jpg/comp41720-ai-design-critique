from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from indexing_worker.consumer import deliver
from indexing_worker.message_handler import MessageAction, MessageDecision


@pytest.mark.parametrize('action', list(MessageAction))
def test_delivery_decisions_preserve_ack_order(action, monkeypatch):
    monkeypatch.setattr('indexing_worker.consumer.time.sleep', lambda _: None)
    channel = Mock()
    handler = Mock()
    handler.handle.return_value = MessageDecision(action, 'S001:1')
    deliver(channel, SimpleNamespace(delivery_tag=7), SimpleNamespace(message_id='S001:1'),
            b'payload', handler, 'local.deadletter')
    if action == MessageAction.REQUEUE:
        channel.basic_nack.assert_called_once_with(7, requeue=True)
        channel.basic_ack.assert_not_called()
    else:
        channel.basic_ack.assert_called_once_with(7)
        if action == MessageAction.DEAD_LETTER:
            assert [c[0] for c in channel.method_calls] == ['basic_publish', 'basic_ack']
            assert channel.basic_publish.call_args.kwargs['mandatory'] is True


def test_failed_quarantine_publish_does_not_ack_original():
    channel = Mock()
    channel.basic_publish.side_effect = RuntimeError('broker unavailable')
    handler = Mock()
    handler.handle.return_value = MessageDecision(MessageAction.DEAD_LETTER)
    with pytest.raises(RuntimeError):
        deliver(channel, SimpleNamespace(delivery_tag=7), SimpleNamespace(message_id=None),
                b'payload', handler, 'local.deadletter')
    channel.basic_ack.assert_not_called()
