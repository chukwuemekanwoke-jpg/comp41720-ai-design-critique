import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

_spec = importlib.util.spec_from_file_location(
    'dead_letter', Path(__file__).resolve().parents[1] / 'docker-check' / 'dead_letter.py')
dead_letter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dead_letter)


def channel_with(*bodies):
    channel = Mock()
    messages = [(SimpleNamespace(delivery_tag=tag), None, body) for tag, body in enumerate(bodies, 1)]
    channel.basic_get.side_effect = messages + [(None, None, None)]
    return channel


def test_marker_is_acked_and_earlier_dead_letters_are_requeued():
    channel = channel_with(b'real-failed-event', b'old-marker', b'marker', b'later-event')
    assert dead_letter.take_quarantined(channel, 'q.deadletter', b'marker') is True
    channel.basic_ack.assert_called_once_with(3)
    assert [c.args for c in channel.basic_nack.call_args_list] == [(1,), (2,)]
    assert all(c.kwargs == {'requeue': True} for c in channel.basic_nack.call_args_list)
    assert channel.basic_get.call_count == 3


def test_missing_marker_consumes_nothing():
    channel = channel_with(b'real-failed-event', b'another')
    assert dead_letter.take_quarantined(channel, 'q.deadletter', b'marker') is False
    channel.basic_ack.assert_not_called()
    assert [c.args for c in channel.basic_nack.call_args_list] == [(1,), (2,)]


def test_held_messages_are_requeued_even_if_the_broker_call_fails():
    channel = Mock()
    channel.basic_get.side_effect = [(SimpleNamespace(delivery_tag=1), None, b'real'), RuntimeError('closed')]
    try:
        dead_letter.take_quarantined(channel, 'q.deadletter', b'marker')
    except RuntimeError:
        pass
    channel.basic_nack.assert_called_once_with(1, requeue=True)
    channel.basic_ack.assert_not_called()
