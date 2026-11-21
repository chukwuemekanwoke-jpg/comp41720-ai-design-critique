"""Injected model failures, shared deadlines and bulkhead recovery."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest

from answer_service.config import Settings
from answer_service.models import AnswerRequest
from answer_service.ollama import OllamaAdapter
from answer_service.service import build_answer


@pytest.fixture
def payload():
    return AnswerRequest.model_validate(json.loads(
        (Path(__file__).resolve().parents[1] / 'data/answer_request_demo.json').read_text()
    ))


def success():
    return httpx.Response(200, json={
        'model': 'test-model', 'done': True, 'done_reason': 'stop',
        'message': {'role': 'assistant', 'content': json.dumps({
            'status': 'answered', 'answer': 'A blue form.',
            'checklist': [], 'source_indices': [1],
        })},
    })


@pytest.mark.parametrize('failure', ['connect', 500, 502, 503, 504])
def test_transient_failure_retries_then_recovers(payload, failure):
    calls = []
    async def handler(request):
        calls.append(request)
        if len(calls) == 1:
            if failure == 'connect':
                raise httpx.ConnectError('injected', request=request)
            return httpx.Response(failure)
        return success()
    async def run():
        async with httpx.AsyncClient(base_url='http://model', transport=httpx.MockTransport(handler)) as client:
            adapter = OllamaAdapter(Settings(retry_backoff_seconds=0), client)
            result = await build_answer(payload, 'recovered', adapter)
            assert result.status == 'answered' and not result.fallback_used
            assert result.sources == [payload.sources[0]]
            assert len(calls) == 2
    asyncio.run(run())


@pytest.mark.parametrize('failure', [400, 404, 429, 'read_timeout', 'malformed'])
def test_terminal_failures_are_not_retried(payload, failure):
    calls = []
    async def handler(request):
        calls.append(request)
        if failure == 'read_timeout':
            raise httpx.ReadTimeout('injected', request=request)
        if failure == 'malformed':
            return httpx.Response(200, text='not json')
        return httpx.Response(failure)
    async def run():
        async with httpx.AsyncClient(base_url='http://model', transport=httpx.MockTransport(handler)) as client:
            result = await build_answer(payload, 'terminal', OllamaAdapter(Settings(), client))
            assert result.status == 'degraded' and result.sources == payload.sources
            assert result.index_version == payload.index_version
            assert len(calls) == 1
    asyncio.run(run())


def test_exhausted_retries_fall_back_and_next_request_can_recover(payload):
    calls = []
    async def handler(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) <= 2 else success()
    async def run():
        async with httpx.AsyncClient(base_url='http://model', transport=httpx.MockTransport(handler)) as client:
            adapter = OllamaAdapter(Settings(retry_backoff_seconds=0), client)
            failed = await build_answer(payload, 'failed', adapter)
            assert failed.status == 'degraded' and failed.sources == payload.sources
            assert len(calls) == 2
            recovered = await build_answer(payload, 'recovered', adapter)
            assert recovered.status == 'answered' and len(calls) == 3
    asyncio.run(run())


def test_deadline_includes_backoff_and_releases_capacity(payload):
    calls = []
    async def handler(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) == 1 else success()
    async def run():
        async with httpx.AsyncClient(base_url='http://model', transport=httpx.MockTransport(handler)) as client:
            adapter = OllamaAdapter(Settings(timeout_seconds=0.02, retry_backoff_seconds=0.2), client)
            result = await asyncio.wait_for(build_answer(payload, 'deadline', adapter), timeout=1)
            assert result.status == 'degraded' and len(calls) == 1
            assert (await build_answer(payload, 'next', adapter)).status == 'answered'
    asyncio.run(run())


def test_bulkhead_falls_back_without_queueing_and_recovers_after_cancellation(payload):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def handler(request):
            calls.append(request)
            entered.set()
            await release.wait()
            return success()
        async with httpx.AsyncClient(base_url='http://model', transport=httpx.MockTransport(handler)) as client:
            adapter = OllamaAdapter(Settings(max_concurrent_generations=1), client)
            first = asyncio.create_task(build_answer(payload, 'first', adapter))
            await asyncio.wait_for(entered.wait(), timeout=1)
            try:
                rejected = await asyncio.wait_for(build_answer(payload, 'busy', adapter), timeout=0.5)
                assert rejected.status == 'degraded' and rejected.sources == payload.sources
                assert rejected.request_id == 'busy' and len(calls) == 1
            finally:
                first.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first
            release.set()
            recovered = await build_answer(payload, 'after-cancel', adapter)
            assert recovered.status == 'answered' and len(calls) == 2
    asyncio.run(run())


@pytest.mark.parametrize('setting', [
    {'max_attempts': 0}, {'max_attempts': 4}, {'max_attempts': True},
    {'retry_backoff_seconds': -1}, {'retry_backoff_seconds': float('nan')},
    {'max_concurrent_generations': 0}, {'max_concurrent_generations': 9},
])
def test_invalid_resilience_settings(setting):
    with pytest.raises(ValueError):
        Settings(**setting)


def test_resilience_settings_from_environment(monkeypatch):
    monkeypatch.setenv('OLLAMA_MAX_ATTEMPTS', '3')
    monkeypatch.setenv('OLLAMA_RETRY_BACKOFF_SECONDS', '0.1')
    monkeypatch.setenv('OLLAMA_MAX_CONCURRENT_GENERATIONS', '2')
    settings = Settings.from_env()
    assert (settings.max_attempts, settings.retry_backoff_seconds,
            settings.max_concurrent_generations) == (3, 0.1, 2)
