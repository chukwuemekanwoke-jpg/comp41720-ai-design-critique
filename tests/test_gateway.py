from fastapi.testclient import TestClient

from gateway.app import app

client = TestClient(app)
Q = "Where are the requirements for moving from Stamp 2 to graduate Stamp 1G?"


def test_answered_shape_and_request_id_header_matches_body():
    r = client.post("/v1/questions", json={"question": Q})
    body = r.json()
    assert r.status_code == 200
    assert body["status"] == "answered" and body["stub"] is True
    assert r.headers["X-Request-ID"] == body["request_id"]
    assert body["sources"] and body["index_version"] and body["last_success_at"]
    assert "not an eligibility decision" in body["notice"]


def test_client_request_id_is_kept_and_unsafe_one_is_replaced():
    ok = client.post("/v1/questions", json={"question": Q}, headers={"X-Request-ID": "abc-123"})
    assert ok.json()["request_id"] == "abc-123"
    bad = client.post("/v1/questions", json={"question": Q}, headers={"X-Request-ID": "a b;c"})
    assert bad.json()["request_id"] != "a b;c"


def test_insufficient_evidence_has_no_answer_or_sources():
    body = client.post("/v1/questions", json={"question": "anything [missing]"}).json()
    assert body["status"] == "insufficient_evidence"
    assert body["answer"] is None and body["sources"] == []


def test_degraded_marks_fallback_and_keeps_evidence():
    body = client.post("/v1/questions", json={"question": "anything [degraded]"}).json()
    assert body["status"] == "degraded" and body["fallback_used"] is True
    assert body["answer"] is None and body["sources"]
    assert body["model"]["name"] == "local-fallback"


def test_invalid_requests_return_400_with_error_shape():
    for payload in ({"question": "hi"}, {"question": "x" * 501}, {}):
        r = client.post("/v1/questions", json=payload)
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_request"
        assert r.json()["request_id"] == r.headers["X-Request-ID"]


def test_health_ready_and_metrics():
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json()["status"] == "ready"
    client.post("/v1/questions", json={"question": Q})
    text = client.get("/metrics").text
    assert 'gateway_requests_total{path="/v1/questions",status="200"}' in text
    assert "gateway_request_duration_seconds_count" in text
