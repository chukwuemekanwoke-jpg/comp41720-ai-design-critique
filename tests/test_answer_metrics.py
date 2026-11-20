"""Metrics describe behaviour without exposing evidence or request identities."""
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from answer_service.app import create_app
from answer_service.config import Settings


def payload(name='answer_request_demo.json'):
    return json.loads((Path(__file__).resolve().parents[1] / 'data' / name).read_text())


def samples(client):
    response = client.get('/metrics')
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/plain')
    return {(s.name, tuple(sorted(s.labels.items()))): s.value
            for family in text_string_to_metric_families(response.text)
            for s in family.samples}


def metric(data, name, **labels):
    return data.get((name, tuple(sorted(labels.items()))), 0)


def test_request_metrics_include_invalid_input_and_exclude_scrapes():
    with TestClient(create_app(Settings())) as client:
        client.get('/healthz')
        samples(client)
        client.post('/v1/answers', json=payload(), headers={'X-Request-ID': 'private-id'})
        client.post('/v1/answers', json={})
        data = samples(client)
        assert metric(data, 'studentpath_answer_requests_total', status_class='2xx') == 1
        assert metric(data, 'studentpath_answer_requests_total', status_class='4xx') == 1
        assert metric(data, 'studentpath_answer_request_duration_seconds_count') == 2
        assert metric(data, 'studentpath_answer_responses_total', status='degraded') == 1
        text = client.get('/metrics').text
        assert 'private-id' not in text and payload()['question'] not in text
        assert payload()['sources'][0]['url'] not in text
    with TestClient(create_app(Settings())) as other:
        assert metric(samples(other), 'studentpath_answer_request_duration_seconds_count') == 0


def test_retry_and_reported_usage_are_exported():
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={
            'model': 'test-model', 'done': True, 'done_reason': 'stop',
            'prompt_eval_count': 37, 'eval_count': 8,
            'message': {'role': 'assistant', 'content': json.dumps({
                'status': 'answered', 'answer': 'A blue form.',
                'checklist': [], 'source_indices': [1],
            })},
        })
    app = create_app(Settings(generation_mode='ollama', retry_backoff_seconds=0),
                     transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        assert client.post('/v1/answers', json=payload()).json()['status'] == 'answered'
        data = samples(client)
        assert metric(data, 'studentpath_answer_model_attempts_total', result='http_5xx') == 1
        assert metric(data, 'studentpath_answer_model_attempts_total', result='http_2xx') == 1
        assert metric(data, 'studentpath_answer_model_retries_total') == 1
        assert metric(data, 'studentpath_answer_model_tokens_total', kind='input') == 37
        assert metric(data, 'studentpath_answer_model_tokens_total', kind='output') == 8
        assert metric(data, 'studentpath_answer_model_active') == 0
        assert metric(data, 'studentpath_answer_responses_total', status='answered') == 1


@pytest.mark.parametrize('count', [None, -1, True, '12'])
def test_missing_or_invalid_usage_is_not_invented(count):
    def handler(request):
        return httpx.Response(200, json={
            'model': 'test', 'done': True, 'done_reason': 'stop',
            'eval_count': count,
            'message': {'role': 'assistant', 'content': 'not valid output'},
        })
    app = create_app(Settings(generation_mode='ollama'), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        assert client.post('/v1/answers', json=payload()).json()['status'] == 'degraded'
        data = samples(client)
        for kind in ('input', 'output'):
            assert metric(data, 'studentpath_answer_model_usage_missing_total', kind=kind) == 1
            assert metric(data, 'studentpath_answer_model_tokens_total', kind=kind) == 0
        assert metric(data, 'studentpath_answer_model_active') == 0


def test_pending_update_counts_response_without_model_attempt():
    def handler(request):
        pytest.fail('Policy response must bypass the model')
    app = create_app(Settings(generation_mode='ollama'), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        client.post('/v1/answers', json=payload('answer_abstention_demo.json'))
        data = samples(client)
        assert metric(data, 'studentpath_answer_responses_total', status='insufficient_evidence') == 1
        assert not any(key[0] == 'studentpath_answer_model_attempts_total' for key in data)
