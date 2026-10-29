"""Gateway boundary checks using synthetic evidence and actual service ASGI APIs."""
import asyncio
import copy
import json
from contextlib import contextmanager
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from answer_service.app import create_app as answer_app
from answer_service.config import Settings as AnswerSettings
from gateway.app import create_app
from gateway.config import Settings
from gateway.models import NOTICE
from retrieval_api.app import create_app as retrieval_app
from retrieval_api.repository import IndexSnapshot, InMemoryPassageRepository, Passage

Q = "Which fictional form is required?"
FRESH = "2026-10-29T12:00:00+00:00"
SOURCE = dict(source_id="SYN001", snapshot_id="SYN001:fixture", source_version=1,
              url="https://www.irishimmigration.ie/synthetic-fixture/",
              passage="Synthetic fixture: the fictional form is blue.")


def repository():
    repo = InMemoryPassageRepository()
    repo.publish(IndexSnapshot("fixture-v1", datetime.fromisoformat(FRESH), (
        Passage(**{key: value for key, value in SOURCE.items() if key != "passage"},
                passage_id="p1", text=SOURCE["passage"]),)))
    return repo


def retrieval_result(request_id="trace-1"):
    return dict(request_id=request_id, index_version="fixture-v1", last_success_at=FRESH,
                passages=[dict(passage_id="p1", text=SOURCE["passage"], score=0.5,
                               **{k: v for k, v in SOURCE.items() if k != "passage"})])


def answer_result(request_id="trace-1", **changes):
    return dict(request_id=request_id, status="answered", answer="A blue form.",
                checklist=["Prepare the fictional blue form."], sources=[SOURCE.copy()],
                index_version="fixture-v1", last_success_at=FRESH, fallback_used=False,
                model=dict(name="synthetic-generator", prompt_version="test"), notice=NOTICE) | changes


def response(body, request_id="trace-1", status=200):
    return httpx.Response(status, json=body, headers={"X-Request-ID": request_id})


@contextmanager
def mocked(retrieval_handler=None, answer_handler=None, **settings):
    retrieval_handler = retrieval_handler or (lambda req: response(retrieval_result()))
    answer_handler = answer_handler or (lambda req: response(answer_result()))
    with TestClient(create_app(Settings(**settings),
                              retrieval_transport=httpx.MockTransport(retrieval_handler),
                              answer_transport=httpx.MockTransport(answer_handler))) as client:
        yield client


@contextmanager
def real_services(repo=None, answer=None, **settings):
    answer = answer or answer_app(AnswerSettings())
    with TestClient(answer), TestClient(create_app(
        Settings(**settings), retrieval_transport=httpx.ASGITransport(app=retrieval_app(repo or repository())),
        answer_transport=httpx.ASGITransport(app=answer),
    )) as client:
        yield client


def ask(client, **kwargs):
    return client.post("/v1/questions", json={"question": Q}, headers={"X-Request-ID": "trace-1"}, **kwargs)


def test_real_apis_preserve_evidence_and_evidence_only_fallback():
    with real_services() as client:
        result = ask(client)
    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "degraded" and body["fallback_used"] is True
    assert body["answer"] is None and body["checklist"] == []
    assert body["sources"] == [SOURCE]
    assert body["index_version"] == "fixture-v1"
    assert datetime.fromisoformat(body["last_success_at"].replace("Z", "+00:00")) == datetime.fromisoformat(FRESH)
    assert result.headers["X-Request-ID"] == body["request_id"] == "trace-1"
    assert "stub" not in body


def test_real_answer_generation_adapter_returns_valid_answer():
    def generate(request):
        return httpx.Response(200, json={"model": "synthetic-generator", "done": True,
            "done_reason": "stop", "message": {"role": "assistant", "content": json.dumps({
                "status": "answered", "answer": "A blue form.",
                "checklist": ["Prepare the fictional blue form."], "source_indices": [1]})}})
    service = answer_app(AnswerSettings(generation_mode="ollama"), transport=httpx.MockTransport(generate))
    with real_services(answer=service) as client:
        result = ask(client)
    assert result.status_code == 200 and result.json()["status"] == "answered"
    assert result.json()["sources"] == [SOURCE] and result.json()["fallback_used"] is False


def test_empty_retrieval_via_real_services_is_not_an_answer():
    with real_services() as client:
        result = client.post("/v1/questions", json={"question": "zzzzzzzz"})
    assert result.status_code == 200
    assert result.json()["status"] == "insufficient_evidence"
    assert result.json()["sources"] == result.json()["checklist"] == []
    assert result.json()["answer"] is None and not result.json()["fallback_used"]


def test_request_mapping_and_single_retrieval():
    calls = []
    def retrieve(request):
        body = json.loads(request.content)
        assert body == {"request_id": "trace-1", "question": Q, "top_k": 5, "index_version": None}
        assert request.headers["X-Request-ID"] == "trace-1"
        calls.append(request.url.path)
        return response(retrieval_result())
    def answer(request):
        assert request.headers["X-Request-ID"] == "trace-1"
        assert json.loads(request.content) == {"question": Q, "sources": [SOURCE],
            "index_version": "fixture-v1", "last_success_at": FRESH}
        calls.append(request.url.path)
        return response(answer_result())
    with mocked(retrieve, answer) as client:
        assert ask(client).status_code == 200
    assert calls == ["/v1/retrieve", "/v1/answers"]


def test_pinned_evidence_survives_new_index_activation():
    repo = repository()
    def answer(request):
        payload = json.loads(request.content)
        if payload["index_version"] == "fixture-v1":
            repo.publish(IndexSnapshot("fixture-v2", datetime(2026, 10, 30, tzinfo=timezone.utc), (
                Passage("p2", "SYN002", "SYN002:fixture", 2, SOURCE["url"],
                        "Synthetic fixture: a fictional green form."),)))
        return response(answer_result(index_version=payload["index_version"],
            last_success_at=payload["last_success_at"], sources=payload["sources"]))
    with TestClient(create_app(Settings(), retrieval_transport=httpx.ASGITransport(app=retrieval_app(repo)),
                              answer_transport=httpx.MockTransport(answer))) as client:
        old = ask(client).json()
        new = ask(client).json()
    assert old["index_version"] == "fixture-v1" and old["sources"] == [SOURCE]
    assert new["index_version"] == "fixture-v2" and new["sources"][0]["source_id"] == "SYN002"
    assert old["last_success_at"] != new["last_success_at"]


@pytest.mark.parametrize("incoming", [None, "bad id;", "x" * 65, "good-id_1"])
def test_request_id_validation_and_propagation(incoming):
    with real_services() as client:
        result = client.post("/v1/questions", json={"question": Q},
                             headers={} if incoming is None else {"X-Request-ID": incoming})
    identifier = result.json()["request_id"]
    assert identifier == result.headers["X-Request-ID"]
    assert identifier == incoming if incoming == "good-id_1" else len(identifier) == 32


@pytest.mark.parametrize("payload", [{}, {"question": "hi"}, {"question": " " * 5},
    {"question": "x" * 501}, {"question": 123}, {"question": Q, "sources": []}])
def test_invalid_questions_do_not_call_services(payload):
    def unexpected(request):
        pytest.fail("Invalid questions must not reach downstream services")
    with mocked(unexpected, unexpected) as client:
        result = client.post("/v1/questions", json=payload)
        assert result.status_code == 400 and result.json()["error"] == "invalid_request"
        assert result.headers["X-Request-ID"] == result.json()["request_id"]


@pytest.mark.parametrize("service", ["retrieval", "answer"])
@pytest.mark.parametrize("status", [302, 400, 404, 503])
def test_upstream_http_failures_are_not_policy_responses(service, status):
    def fail(request):
        return httpx.Response(status, headers={"Location": "http://example.invalid/private"})
    with mocked(**{service + "_handler": fail}) as client:
        result = ask(client)
    assert result.status_code == 502 and result.json()["error"] == "upstream_unavailable"
    assert result.json()["request_id"] == "trace-1"


def test_connection_failure_does_not_leak_internal_details():
    def fail(request):
        raise httpx.ConnectError("secret-internal-address", request=request)
    with mocked(retrieval_handler=fail) as client:
        result = ask(client)
    assert result.status_code == 502 and "secret-internal-address" not in result.text


@pytest.mark.parametrize("service", ["retrieval", "answer"])
def test_per_call_deadlines(service):
    async def slow(request):
        await asyncio.sleep(0.1)
        return response(retrieval_result() if service == "retrieval" else answer_result())
    with mocked(**{service + "_handler": slow, service + "_timeout": 0.01}) as client:
        result = ask(client)
    assert result.status_code == 504 and result.json()["error"] == "upstream_timeout"


def test_total_deadline_bounds_combined_calls():
    async def retrieve(request):
        await asyncio.sleep(0.04)
        return response(retrieval_result())
    async def answer(request):
        await asyncio.sleep(0.04)
        return response(answer_result())
    with mocked(retrieve, answer, retrieval_timeout=0.055, answer_timeout=0.055, total_timeout=0.06) as client:
        assert ask(client).status_code == 504


@pytest.mark.parametrize("change", [
    lambda b: b.update(index_version="wrong"), lambda b: b.update(request_id="wrong"),
    lambda b: b.update(last_success_at="2026-10-30T12:00:00Z"),
    lambda b: b.update(last_success_at="2026-10-29T12:00:00"),
    lambda b: b["sources"][0].update(passage="Invented evidence"),
    lambda b: b["sources"][0].update(url="https://example.invalid/forged"),
    lambda b: b["sources"][0].update(source_version=99),
    lambda b: b["sources"].append(b["sources"][0].copy()),
    lambda b: b.update(answer=None), lambda b: b.update(fallback_used=True),
    lambda b: b.update(status="insufficient_evidence", answer=None, checklist=[]),
    lambda b: b.update(status="degraded", answer=None, checklist=[], sources=[], fallback_used=True),
    lambda b: b.update(stub=True),
])
def test_untrusted_answer_fields_fail_closed(change):
    body = copy.deepcopy(answer_result())
    change(body)
    with mocked(answer_handler=lambda request: response(body)) as client:
        result = ask(client)
    assert result.status_code == 502 and "answer" not in result.json()


@pytest.mark.parametrize("change", [
    lambda b: b.update(request_id="wrong"), lambda b: b.update(index_version=" "),
    lambda b: b.update(last_success_at="2026-10-29T12:00:00"),
    lambda b: b["passages"][0].update(text="x" * 4001),
    lambda b: b["passages"][0].update(score=2),
    lambda b: b["passages"].append(b["passages"][0].copy()),
])
def test_invalid_retrieval_is_rejected_before_answer(change):
    body = copy.deepcopy(retrieval_result())
    change(body)
    def unexpected(request):
        pytest.fail("Invalid evidence cannot reach Answer")
    with mocked(lambda request: response(body), unexpected) as client:
        assert ask(client).status_code == 502


@pytest.mark.parametrize("handler", [
    lambda request: httpx.Response(200, text="not-json", headers={"X-Request-ID": "trace-1"}),
    lambda request: response(retrieval_result(), request_id="wrong"),
    lambda request: httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1), headers={"X-Request-ID": "trace-1"}),
])
def test_malformed_oversize_and_mismatched_transport_responses(handler):
    with mocked(retrieval_handler=handler) as client:
        assert ask(client).status_code == 502


def test_valid_refusal_preserved_even_when_retrieval_has_matches():
    with mocked(answer_handler=lambda request: response(answer_result(
        status="insufficient_evidence", answer=None, checklist=[], sources=[]))) as client:
        result = ask(client)
    assert result.status_code == 200 and result.json()["status"] == "insufficient_evidence"


def test_health_readiness_and_metrics_with_real_apis():
    with real_services() as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").json()["status"] == "ready"
        ask(client)
        assert 'gateway_requests_total{path="/v1/questions",status="200"}' in client.get("/metrics").text
    with TestClient(create_app(Settings(), retrieval_transport=httpx.ASGITransport(app=retrieval_app()),
                              answer_transport=httpx.MockTransport(lambda request: httpx.Response(503)))) as client:
        result = client.get("/readyz")
        assert result.status_code == 503
        assert result.json()["dependencies"] == {"retrieval_api": "unavailable", "answer_service": "unavailable"}
        assert client.get("/healthz").status_code == 200


def test_cors_allows_only_configured_origin_and_exposes_request_id():
    with real_services(cors_origins=("http://localhost:8080",)) as client:
        allowed = client.options("/v1/questions", headers={"Origin": "http://localhost:8080",
            "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type,x-request-id"})
        assert allowed.status_code == 200
        assert allowed.headers["Access-Control-Allow-Origin"] == "http://localhost:8080"
        denied = client.options("/v1/questions", headers={"Origin": "http://other.invalid",
            "Access-Control-Request-Method": "POST"})
        assert denied.status_code == 400 and "Access-Control-Allow-Origin" not in denied.headers
        result = client.post("/v1/questions", json={"question": Q}, headers={"Origin": "http://localhost:8080"})
        assert result.headers["Access-Control-Expose-Headers"] == "X-Request-ID"


@pytest.mark.parametrize("settings", [{"retrieval_url": "file:///tmp"},
    {"answer_url": "https://user:secret@example.invalid"}, {"cors_origins": ("*",)},
    {"total_timeout": float("nan")}, {"retrieval_timeout": 0}, {"total_timeout": 1}])
def test_invalid_configuration_fails_early(settings):
    with pytest.raises(ValueError):
        Settings(**settings)
