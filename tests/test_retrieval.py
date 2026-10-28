"""Retrieval contract, ranking, provenance and ADR-0003 consistency checks."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event

import pytest
from fastapi.testclient import TestClient

from retrieval_api.app import create_app, create_demo_app
from retrieval_api.repository import (
    IndexSnapshot, IndexUnavailable, InMemoryPassageRepository, Passage,
)

TIME = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


def passage(pid, text, version=1):
    return Passage(pid, "S001", f"S001:snapshot-{version}", version,
                   "https://www.irishimmigration.ie/", text)


def snapshot(version="idx-001", passages=None):
    return IndexSnapshot(version, TIME, tuple(passages) if passages is not None else (
        passage("p-b", "Stamp 1G graduate requirements"),
        passage("p-a", "Graduate requirements checklist"),
        passage("p-c", "Registration renewal appointment"),
    ))


@pytest.fixture
def repository():
    repo = InMemoryPassageRepository()
    repo.publish(snapshot())
    return repo


def retrieve(client, **overrides):
    payload = {"request_id": "abc123", "question": "Stamp 1G graduate requirements", "top_k": 5}
    payload.update(overrides)
    return client.post("/v1/retrieve", json=payload)


def test_contract_ranking_and_exact_provenance(repository):
    response = retrieve(TestClient(create_app(repository)))
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"request_id", "index_version", "last_success_at", "passages"}
    assert response.headers["X-Request-ID"] == body["request_id"] == "abc123"
    assert body["index_version"] == "idx-001"
    assert datetime.fromisoformat(body["last_success_at"].replace("Z", "+00:00")) == TIME
    assert [p["passage_id"] for p in body["passages"]] == ["p-b", "p-a"]
    assert body["passages"][0] == {**vars(repository.pin().passages[0]), "score": 1.0}
    assert body["passages"][1]["score"] == 0.5


def test_case_punctuation_duplicate_terms_and_stable_ties(repository):
    client = TestClient(create_app(repository))
    response = retrieve(client, question="GRADUATE, graduate REQUIREMENTS!")
    assert [p["passage_id"] for p in response.json()["passages"]] == ["p-a", "p-b"]
    assert all(p["score"] == 1 for p in response.json()["passages"])
    assert len(retrieve(client, top_k=1).json()["passages"]) == 1


@pytest.mark.parametrize("question", ["unmatchedword", "the and for", "!!!"])
def test_no_evidence_is_empty(repository, question):
    response = retrieve(TestClient(create_app(repository)), question=question)
    assert response.status_code == 200
    assert response.json()["passages"] == []


@pytest.mark.parametrize("overrides", [
    {"question": "  "}, {"question": "hi"}, {"question": "x" * 501},
    {"question": None}, {"top_k": 0}, {"top_k": 21}, {"top_k": True},
    {"top_k": 1.5}, {"top_k": "5"}, {"index_version": " "},
    {"request_id": "bad id"}, {"request_id": "x" * 65}, {"unexpected": True},
])
def test_validation(repository, overrides):
    response = retrieve(TestClient(create_app(repository)), **overrides)
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_missing_fields_and_malformed_json(repository):
    client = TestClient(create_app(repository))
    for kwargs in ({"json": {}}, {"json": {"question": "requirements"}},
                   {"content": "{", "headers": {"Content-Type": "application/json"}}):
        response = client.post("/v1/retrieve", **kwargs)
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_request"


def test_explicit_version_never_falls_back(repository):
    repository.publish(snapshot("idx-002", [passage("new", "Graduate requirements", 2)]))
    client = TestClient(create_app(repository))
    assert retrieve(client).json()["index_version"] == "idx-002"
    old = retrieve(client, index_version="idx-001").json()
    assert old["index_version"] == "idx-001"
    assert old["passages"][0]["source_version"] == 1
    missing = retrieve(client, index_version="not-retained")
    assert missing.status_code == 404
    assert missing.json()["error"] == "index_version_not_found"


def test_unavailable_index_and_storage_failure():
    class BrokenRepository:
        def pin(self, index_version=None):
            raise IndexUnavailable("private storage details")

    for repo in (None, InMemoryPassageRepository(), BrokenRepository()):
        response = retrieve(TestClient(create_app(repo)))
        assert response.status_code == 503
        assert response.json()["error"] == "index_unavailable"
        assert "private" not in response.text


def test_empty_committed_index_is_available(repository):
    repository.publish(snapshot("empty", []))
    response = retrieve(TestClient(create_app(repository)))
    assert response.status_code == 200
    assert response.json()["passages"] == []


def test_publication_immutable_staged_build_and_rollback(repository):
    with pytest.raises(ValueError, match="immutable"):
        repository.publish(snapshot())
    repository.publish(snapshot("idx-002"), activate=False)
    assert repository.pin().index_version == "idx-001"
    repository.activate("idx-002")
    assert repository.pin().index_version == "idx-002"
    repository.activate("idx-001")
    assert repository.pin().index_version == "idx-001"


def test_inflight_request_keeps_old_evidence_and_freshness_during_swap(repository):
    pinned, release = Event(), Event()

    class PausingRepository:
        calls = 0

        def pin(self, index_version=None):
            self.calls += 1
            view = repository.pin(index_version)
            pinned.set()
            assert release.wait(timeout=5)
            return view

    adapter = PausingRepository()
    client = TestClient(create_app(adapter))
    new_time = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(retrieve, client)
        try:
            assert pinned.wait(timeout=5)
            # A candidate under construction cannot affect the committed view.
            candidate = IndexSnapshot("idx-002", new_time, (
                passage("new", "Stamp 1G graduate requirements revised", 2),))
            repository.publish(candidate)
        finally:
            release.set()
        old = pending.result(timeout=5).json()
    assert adapter.calls == 1
    assert old["index_version"] == "idx-001"
    assert all(p["source_version"] == 1 for p in old["passages"])
    assert datetime.fromisoformat(old["last_success_at"].replace("Z", "+00:00")) == TIME
    new = retrieve(client).json()
    assert new["index_version"] == "idx-002"
    assert new["passages"][0]["source_version"] == 2
    assert datetime.fromisoformat(new["last_success_at"].replace("Z", "+00:00")) == new_time


def test_snapshot_copies_input_and_rejects_ambiguous_metadata():
    items = [passage("p-1", "Graduate requirements")]
    view = IndexSnapshot("idx-001", TIME, items)
    items.clear()
    assert len(view.passages) == 1
    with pytest.raises(ValueError, match="unique"):
        snapshot(passages=[view.passages[0], view.passages[0]])
    with pytest.raises(ValueError, match="timezone"):
        IndexSnapshot("idx-001", datetime(2026, 10, 27), ())


def test_demo_is_explicit_and_labelled_synthetic():
    client = TestClient(create_demo_app())
    body = retrieve(client).json()
    assert body["index_version"].startswith("demo-")
    assert all(p["text"].startswith("Synthetic demo only:") for p in body["passages"])
    assert client.get("/healthz").json() == {"status": "ok"}
