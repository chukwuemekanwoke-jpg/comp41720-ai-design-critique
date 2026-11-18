"""ADR-0003 pending-change abstention across Retrieval, Gateway and Answer."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from answer_service.app import create_app as answer_app
from answer_service.config import Settings as AnswerSettings
from gateway.app import create_app as gateway_app
from gateway.config import Settings
from retrieval_api.app import create_app as retrieval_app
from retrieval_api.freshness import (CollectorStatusClient, SourceStatus, SourceStatusCache,
                                     StatusPoller, assess)
from retrieval_api.repository import IndexSnapshot, InMemoryPassageRepository, Passage

NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
CHANGED_AT = "2026-11-09T11:30:00+00:00"
FORM = Passage("p1", "SYN001", "SYN001:fixture", 2, "https://www.irishimmigration.ie/form/",
               "Synthetic fixture: the fictional form is blue.")
FEE = Passage("p2", "SYN002", "SYN002:fixture", 1, "https://www.irishimmigration.ie/fee/",
              "Synthetic fixture: the fictional fee is ten euro.")


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


def cache_with(*statuses, clock=None):
    cache = SourceStatusCache(clock=clock or Clock())
    for status in statuses:
        cache.put(status)
    return cache


# --- the rule itself -------------------------------------------------------

def test_newer_collector_version_is_pending():
    report = assess([FORM, FEE], cache_with(SourceStatus("SYN001", 3, CHANGED_AT),
                                            SourceStatus("SYN002", 1, None)))
    assert [p.source_id for p in report.pending] == ["SYN001"]
    assert report.pending[0].indexed_source_version == 2
    assert report.pending[0].latest_source_version == 3
    assert report.pending[0].detected_at == CHANGED_AT
    assert report.confirmed


def test_same_version_is_not_pending():
    report = assess([FORM], cache_with(SourceStatus("SYN001", 2, CHANGED_AT)))
    assert report.pending == () and report.confirmed


def test_missing_status_is_unconfirmed_not_pending():
    report = assess([FORM, FEE], cache_with(SourceStatus("SYN001", 2, None)))
    assert report.pending == () and not report.confirmed


def test_old_status_is_unconfirmed_not_pending():
    clock = Clock()
    cache = cache_with(SourceStatus("SYN001", 3, CHANGED_AT), clock=clock)
    clock.now = NOW + timedelta(seconds=61)
    report = assess([FORM], cache)
    assert report.pending == () and not report.confirmed


# --- reading the Collector -------------------------------------------------

def collector(routes):
    def handle(request):
        status, body = routes[request.url.path]
        return httpx.Response(status, json=body)
    return CollectorStatusClient("http://collector", transport=httpx.MockTransport(handle))


def test_poller_stores_known_sources_and_forgets_unknown_ones():
    client = collector({
        "/sources/SYN001/status": (200, {"source_id": "SYN001", "source_version": 3, "detected_at": CHANGED_AT}),
        "/sources/SYN002/status": (404, {"detail": "Source not found"}),
    })
    cache = cache_with(SourceStatus("SYN002", 1, None))
    StatusPoller(cache, client.fetch, lambda: ["SYN001", "SYN002"]).poll_once()
    assert cache.get("SYN001") == SourceStatus("SYN001", 3, CHANGED_AT)
    assert cache.get("SYN002") is None


def test_collector_error_keeps_last_known_status():
    client = collector({"/sources/SYN001/status": (503, {"detail": "unavailable"})})
    cache = cache_with(SourceStatus("SYN001", 2, None))
    StatusPoller(cache, client.fetch, lambda: ["SYN001"]).poll_once()
    assert cache.get("SYN001") == SourceStatus("SYN001", 2, None)


def test_status_for_another_source_is_rejected():
    client = collector({"/sources/SYN001/status": (200, {"source_id": "OTHER", "source_version": 9})})
    with pytest.raises(ValueError):
        client.fetch("SYN001")


# --- end to end through the real services ----------------------------------

def services(cache):
    repo = InMemoryPassageRepository()
    repo.publish(IndexSnapshot("idx-2", NOW, (FORM, FEE)))
    model_calls = []

    def model(request):
        model_calls.append(request)
        return httpx.Response(500)

    answer = answer_app(AnswerSettings(generation_mode="ollama"), transport=httpx.MockTransport(model))
    gateway = gateway_app(Settings(),
                          retrieval_transport=httpx.ASGITransport(app=retrieval_app(repo, cache)),
                          answer_transport=httpx.ASGITransport(app=answer))
    return answer, gateway, model_calls


def ask(question):
    answer, gateway, calls = services(cache_with(SourceStatus("SYN001", 3, CHANGED_AT),
                                                 SourceStatus("SYN002", 1, None)))
    with TestClient(answer), TestClient(gateway) as client:
        response = client.post("/v1/questions", json={"question": question})
    assert response.status_code == 200, response.text
    return response.json(), calls


def test_question_using_changed_source_abstains_without_calling_the_model():
    body, calls = ask("Which fictional form is required?")
    assert body["status"] == "insufficient_evidence"
    assert body["answer"] is None and body["sources"] == []
    affected = body["abstention"]["affected_sources"]
    assert [(a["source_id"], a["detected_at"], a["url"]) for a in affected] == [
        ("SYN001", CHANGED_AT, FORM.url)]
    assert body["abstention"]["reason"] == "pending_source_update"
    assert calls == []


def test_question_using_unaffected_source_answers_normally():
    # Shares no words with the changed page, so only the unaffected source is retrieved.
    body, calls = ask("Ten euro fee?")
    assert body["abstention"] is None and body["status"] == "degraded"
    assert [s["source_id"] for s in body["sources"]] == ["SYN002"]
    assert len(calls) >= 1  # the model was asked (then fell back to evidence)


def test_gateway_rejects_an_answer_that_ignores_the_decision():
    retrieval = {"request_id": "trace-1", "index_version": "idx-2", "last_success_at": NOW.isoformat(),
                 "passages": [{**vars(FORM), "score": 1.0}],
                 "pending_sources": [{"source_id": "SYN001", "indexed_source_version": 2,
                                      "latest_source_version": 3, "detected_at": CHANGED_AT}],
                 "freshness_confirmed": True}
    sent = {}

    def answer(request):
        sent.update(json.loads(request.content))
        return httpx.Response(200, headers={"X-Request-ID": "trace-1"}, json={
            "request_id": "trace-1", "status": "insufficient_evidence", "answer": None, "checklist": [],
            "sources": [], "index_version": "idx-2", "last_success_at": NOW.isoformat(),
            "fallback_used": False, "model": {"name": "stub", "prompt_version": "none"},
            "notice": "Information only. This is not an eligibility decision or legal advice."})

    gateway = gateway_app(Settings(), retrieval_transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=retrieval, headers={"X-Request-ID": "trace-1"})),
        answer_transport=httpx.MockTransport(answer))
    with TestClient(gateway) as client:
        response = client.post("/v1/questions", json={"question": "Which fictional form?"},
                               headers={"X-Request-ID": "trace-1"})
    assert sent["abstention"]["affected_sources"][0]["detected_at"] == CHANGED_AT
    assert response.status_code == 502
