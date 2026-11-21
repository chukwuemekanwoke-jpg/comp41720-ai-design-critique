"""Persistent admission quota: restart, UTC reset, concurrent processes and API fallback."""
import asyncio
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import multiprocessing
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import httpx
import pytest

from answer_service.app import create_app
from answer_service.budget import BudgetExhausted, BudgetUnavailable, DailyTokenBudget
from answer_service.config import Settings
from answer_service.models import AnswerRequest
from answer_service.ollama import OllamaAdapter
from answer_service.service import build_answer

NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
ALLOWANCE = 8192 + 256
ROOT = Path(__file__).resolve().parents[1]


def payload(name='answer_request_demo.json'):
    return json.loads((ROOT / 'data' / name).read_text())


def success():
    return httpx.Response(200, json={'model': 'test', 'done': True, 'done_reason': 'stop',
        'message': {'role': 'assistant', 'content': json.dumps({'status': 'answered',
                     'answer': 'A blue form.', 'checklist': [], 'source_indices': [1]})}})


def rows(path):
    with sqlite3.connect(path) as connection:
        return connection.execute('SELECT day,charged FROM daily_usage ORDER BY day').fetchall()


def test_restart_and_reduced_limit_never_reset_usage(tmp_path):
    path = tmp_path / 'quota.sqlite3'
    assert DailyTokenBudget(path, 20, clock=lambda: NOW).charge(12) == 8
    assert DailyTokenBudget(path, 20, clock=lambda: NOW).charge(8) == 0
    with pytest.raises(BudgetExhausted):
        DailyTokenBudget(path, 20, clock=lambda: NOW).charge(1)
    with pytest.raises(BudgetExhausted):
        DailyTokenBudget(path, 10, clock=lambda: NOW).charge(1)
    assert rows(path) == [('2026-11-18', 20)]


def test_quota_resets_on_utc_day_not_restart_or_local_date(tmp_path):
    path = tmp_path / 'quota.sqlite3'
    now = NOW.replace(hour=23, minute=59)
    clock = lambda: now
    budget = DailyTokenBudget(path, 10, clock=clock)
    budget.charge(10)
    now = datetime(2026,11,19,0,30,tzinfo=timezone(timedelta(hours=1)))  # Still Nov 18 UTC.
    with pytest.raises(BudgetExhausted):
        budget.charge(1)
    now = datetime(2026,11,19,0,0,tzinfo=timezone.utc)
    assert budget.charge(10) == 0
    assert rows(path) == [('2026-11-18',10),('2026-11-19',10)]


def process_charges(path):
    admitted = 0
    for _ in range(10):
        try:
            DailyTokenBudget(path,50,clock=lambda: NOW).charge(10)
        except BudgetExhausted:
            continue
        admitted += 1
    return admitted


def test_independent_processes_cannot_overspend_one_store(tmp_path):
    path = tmp_path / 'shared.sqlite3'
    DailyTokenBudget(path,50,clock=lambda: NOW).charge(10)
    with ProcessPoolExecutor(max_workers=3, mp_context=multiprocessing.get_context('spawn')) as pool:
        admitted = sum(pool.map(process_charges,[str(path)]*3,timeout=20))
    assert admitted == 4
    assert rows(path) == [('2026-11-18',50)]


@pytest.mark.parametrize('kind', ['directory', 'corrupt'])
def test_invalid_store_is_unavailable_not_unlimited(tmp_path, kind):
    path = tmp_path / 'quota.sqlite3'
    path.mkdir() if kind == 'directory' else path.write_bytes(b'not a SQLite store')
    with pytest.raises(BudgetUnavailable):
        DailyTokenBudget(path,10).charge(1)


def test_api_budget_survives_app_restart_and_missing_usage(tmp_path):
    path = tmp_path / 'quota.sqlite3'
    config = Settings(generation_mode='ollama',daily_token_limit=ALLOWANCE,daily_budget_db=str(path))
    calls=[]
    def model(request):
        calls.append(request)
        return success()  # Deliberately omits usage fields; no refund.
    with TestClient(create_app(config,transport=httpx.MockTransport(model))) as client:
        assert client.post('/v1/answers',json=payload()).json()['status']=='answered'
    with TestClient(create_app(config,transport=httpx.MockTransport(model))) as client:
        response = client.post('/v1/answers',json=payload(),headers={'X-Request-ID':'quota-test'})
        body=response.json()
        assert response.status_code==200 and body['status']=='degraded'
        assert body['answer'] is None and body['sources']==payload()['sources']
        assert body['fallback_used'] and body['index_version']==payload()['index_version']
        assert body['request_id']==response.headers['X-Request-ID']=='quota-test'
        assert 'studentpath_answer_budget_rejections_total{reason="exhausted"} 1.0' in client.get('/metrics').text
    assert len(calls)==1
    assert rows(path)[0][1]==ALLOWANCE


def test_retry_requires_its_own_allowance_and_persistent_failure_is_charged(tmp_path):
    path = tmp_path / 'quota.sqlite3'
    config = Settings(generation_mode='ollama',daily_token_limit=ALLOWANCE,
                      daily_budget_db=str(path),retry_backoff_seconds=0)
    calls=[]
    def unavailable(request):
        calls.append(request)
        return httpx.Response(503)
    with TestClient(create_app(config,transport=httpx.MockTransport(unavailable))) as client:
        body=client.post('/v1/answers',json=payload()).json()
        assert body['status']=='degraded' and body['sources']==payload()['sources']
    assert len(calls)==1  # The second attempt was denied before HTTP.
    assert rows(path)[0][1]==ALLOWANCE


def test_two_charges_cover_retry_then_success(tmp_path):
    path = tmp_path / 'quota.sqlite3';calls=[]
    config = Settings(generation_mode='ollama',daily_token_limit=2*ALLOWANCE,
                      daily_budget_db=str(path),retry_backoff_seconds=0)
    def model(request):
        calls.append(request)
        return httpx.Response(503) if len(calls)==1 else success()
    with TestClient(create_app(config,transport=httpx.MockTransport(model))) as client:
        assert client.post('/v1/answers',json=payload()).json()['status']=='answered'
    assert len(calls)==2 and rows(path)[0][1]==2*ALLOWANCE


def test_unavailable_ledger_returns_evidence_without_model_call(tmp_path):
    config = Settings(generation_mode='ollama',daily_budget_db=str(tmp_path))
    def unexpected(request):
        pytest.fail('Unavailable budget must never allow generation')
    with TestClient(create_app(config,transport=httpx.MockTransport(unexpected))) as client:
        body=client.post('/v1/answers',json=payload()).json()
        assert body['status']=='degraded' and body['sources']==payload()['sources']
        assert 'studentpath_answer_budget_rejections_total{reason="unavailable"} 1.0' in client.get('/metrics').text


@pytest.mark.parametrize('case', ['empty', 'pending', 'evidence_only'])
def test_model_bypass_does_not_charge_budget(tmp_path, case):
    path = tmp_path / 'quota.sqlite3'
    config = Settings(generation_mode='evidence_only' if case=='evidence_only' else 'ollama',daily_budget_db=str(path))
    p=payload('answer_abstention_demo.json' if case=='pending' else 'answer_request_demo.json')
    if case=='empty':p.update(sources=[],last_success_at=None)
    with TestClient(create_app(config,transport=httpx.MockTransport(lambda r: pytest.fail('No model expected')))) as client:
        assert client.post('/v1/answers',json=p).status_code==200
    assert not path.exists()


def test_cancelled_attempt_keeps_charge_and_releases_concurrency(tmp_path):
    async def run():
        entered = asyncio.Event()
        async def model(request):
            entered.set()
            await asyncio.Event().wait()
        path=tmp_path/'cancelled.sqlite3'
        config=Settings(daily_token_limit=ALLOWANCE,daily_budget_db=str(path))
        async with httpx.AsyncClient(base_url='http://model',transport=httpx.MockTransport(model)) as client:
            adapter=OllamaAdapter(config,client)
            p=AnswerRequest.model_validate(payload())
            task=asyncio.create_task(build_answer(p,'cancelled',adapter))
            await asyncio.wait_for(entered.wait(),timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
            result=await build_answer(p,'next',adapter)
            assert result.status=='degraded'
            assert rows(path)[0][1]==ALLOWANCE
            assert adapter.metrics.registry.get_sample_value('studentpath_answer_model_active')==0
    asyncio.run(run())


@pytest.mark.parametrize('setting', [
    {'daily_token_limit':0}, {'daily_token_limit':True}, {'daily_token_limit':-1},
    {'daily_token_limit':1_000_000_001}, {'daily_budget_db':''}, {'daily_budget_db':':memory:'},
])
def test_invalid_daily_budget_configuration(setting):
    with pytest.raises(ValueError):Settings(**setting)


def test_daily_budget_settings_from_environment(monkeypatch):
    monkeypatch.setenv('ANSWER_DAILY_TOKEN_LIMIT','50000')
    monkeypatch.setenv('ANSWER_DAILY_BUDGET_DB','custom/ledger.sqlite3')
    c=Settings.from_env()
    assert c.daily_token_limit==50000 and c.daily_budget_db=='custom/ledger.sqlite3'


def test_concurrent_api_requests_share_quota_before_model_admission(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    path=tmp_path/'concurrent.sqlite3'
    config=Settings(generation_mode='ollama',daily_token_limit=ALLOWANCE,
                    daily_budget_db=str(path),max_concurrent_generations=2)
    calls=[]
    async def model(request):
        calls.append(request)
        await asyncio.sleep(0.05)
        return success()
    with TestClient(create_app(config,transport=httpx.MockTransport(model))) as client:
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses=list(pool.map(lambda _: client.post('/v1/answers',json=payload()).json()['status'],range(2)))
        assert sorted(statuses)==['answered','degraded']
        metrics=client.get('/metrics').text
        assert 'studentpath_answer_budget_rejections_total{reason="exhausted"} 1.0' in metrics
        assert 'studentpath_answer_model_rejected_total 0.0' in metrics
    assert len(calls)==1 and rows(path)[0][1]==ALLOWANCE
