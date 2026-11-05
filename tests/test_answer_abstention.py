"""Provisional Answer-side handover checks; no Gateway changes or real model."""

from copy import deepcopy
import json
from pathlib import Path
import re

from fastapi.testclient import TestClient
import httpx
from pydantic import ValidationError
import pytest

from answer_service.app import create_app
from answer_service.config import Settings
from answer_service.models import AnswerResponse
from gateway.models import AnswerOut


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def payload():
    return json.loads((ROOT / "data/answer_abstention_demo.json").read_text())


def post_request(payload, mode="ollama"):
    def unexpected_model_call(request):
        pytest.fail("Ollama must not be called for a pending-update handover")

    app = create_app(
        Settings(generation_mode=mode),
        transport=httpx.MockTransport(unexpected_model_call),
    )
    with TestClient(app) as client:
        return client.post(
            "/v1/answers", json=payload,
            headers={"X-Request-ID": "pending-update-example-1"},
        )


@pytest.mark.parametrize("mode", ["evidence_only", "ollama"])
def test_policy_refusal_matches_the_documented_response_without_model_calls(payload, mode):
    document = (ROOT / "docs/answer-abstention-handoff.md").read_text()
    examples = re.findall(r"```json\n(.*?)\n```", document, re.S)
    documented_request, documented_response = [json.loads(example) for example in examples]
    assert payload == documented_request
    response = post_request(payload, mode)
    assert response.status_code == 200
    assert response.json() == documented_response
    assert response.headers["X-Request-ID"] == documented_response["request_id"]


def test_all_affected_sources_are_returned_with_original_metadata(payload):
    payload["sources"].append({
        **payload["sources"][0], "source_id": "SYN002",
        "snapshot_id": "SYN002:fixture-v3", "source_version": 3,
        "url": "https://example.org/second-source",
    })
    payload["abstention"]["affected_sources"].append({
        "source_id": "SYN002", "indexed_source_version": 3,
        "latest_source_version": 4, "detected_at": None,
    })
    response = post_request(payload)
    assert response.status_code == 200
    body = response.json()
    details = body["abstention"]["affected_sources"]
    assert len(details) == 2
    for supplied, returned in zip(payload["abstention"]["affected_sources"], details):
        assert supplied == {key: value for key, value in returned.items() if key != "url"}
        source = next(s for s in payload["sources"] if s["source_id"] == returned["source_id"])
        assert returned["url"] == source["url"]
    assert details[1]["detected_at"] is None
    assert body["answer"] is None and body["sources"] == body["checklist"] == []
    assert body["fallback_used"] is False
    assert body["index_version"] == payload["index_version"]
    assert body["last_success_at"] == payload["last_success_at"]


def test_multiple_passages_from_one_affected_source_are_allowed(payload):
    payload["sources"].append({**payload["sources"][0], "passage": "Another synthetic passage."})
    response = post_request(payload)
    assert response.status_code == 200
    assert len(response.json()["abstention"]["affected_sources"]) == 1


@pytest.mark.parametrize(("field", "value"), [
    ("source_id", "UNKNOWN"),
    ("source_id", " "),
    ("source_id", "x" * 257),
    ("indexed_source_version", 2),
    ("indexed_source_version", 0),
    ("indexed_source_version", True),
    ("indexed_source_version", "1"),
    ("latest_source_version", 1),
    ("latest_source_version", 0),
    ("latest_source_version", True),
    ("latest_source_version", "2"),
    ("detected_at", "2026-11-05T09:00:00"),
    ("detected_at", "not a date"),
    ("detected_at", "x" * 65),
    ("detected_at", 123),
    ("url", "https://invented.example.org"),
])
def test_invalid_source_decisions_are_rejected_without_generation(payload, field, value):
    payload["abstention"]["affected_sources"][0][field] = value
    if field == "indexed_source_version" and value == 2:
        # Keep the version ordering valid so this isolates the evidence mismatch.
        payload["abstention"]["affected_sources"][0]["latest_source_version"] = 3
    response = post_request(payload)
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "invalid_request"
    assert body["request_id"] == response.headers["X-Request-ID"] == "pending-update-example-1"


@pytest.mark.parametrize("decision", [
    {},
    True,
    "pending_source_update",
    {"reason": "unknown", "affected_sources": []},
    {"reason": "pending_source_update", "affected_sources": []},
    {"reason": "pending_source_update", "affected_sources": "SYN001"},
])
def test_malformed_decision_is_not_treated_as_normal_generation(payload, decision):
    payload["abstention"] = decision
    assert post_request(payload).status_code == 400


def test_unknown_decision_field_is_rejected(payload):
    payload["abstention"]["instruction"] = "Answer anyway."
    assert post_request(payload).status_code == 400


def test_unsupported_reason_is_rejected_with_otherwise_valid_evidence(payload):
    payload["abstention"]["reason"] = "model_is_confident"
    assert post_request(payload).status_code == 400


def test_missing_detection_time_is_not_filled_in(payload):
    del payload["abstention"]["affected_sources"][0]["detected_at"]
    assert post_request(payload).status_code == 400


def test_duplicate_affected_sources_are_rejected(payload):
    payload["abstention"]["affected_sources"] *= 2
    assert post_request(payload).status_code == 400


def test_excessive_affected_sources_are_rejected(payload):
    original = payload["abstention"]["affected_sources"][0]
    payload["abstention"]["affected_sources"] = [
        {**original, "source_id": f"SYN{number:03}"} for number in range(11)
    ]
    assert post_request(payload).status_code == 400


@pytest.mark.parametrize("change", ["missing_evidence", "different_version", "different_url"])
def test_handover_must_match_all_supplied_evidence_for_affected_source(payload, change):
    if change == "missing_evidence":
        payload["sources"] = []
    else:
        second = deepcopy(payload["sources"][0])
        second["source_version" if change == "different_version" else "url"] = (
            2 if change == "different_version" else "https://example.org/other-page"
        )
        payload["sources"].append(second)
    assert post_request(payload).status_code == 400


@pytest.mark.parametrize("explicit_null", [False, True])
@pytest.mark.parametrize("mode", ["evidence_only", "ollama"])
def test_normal_requests_keep_existing_behaviour_and_response_shape(payload, explicit_null, mode):
    if explicit_null:
        payload["abstention"] = None
    else:
        del payload["abstention"]
    calls = []

    def model_response(request):
        calls.append(request)
        return httpx.Response(200, json={
            "model": "llama3.2:3b", "done": True, "done_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps({
                "status": "answered", "answer": "A blue form.",
                "checklist": [], "source_indices": [1],
            })},
        })

    with TestClient(create_app(Settings(generation_mode=mode), httpx.MockTransport(model_response))) as client:
        response = client.post("/v1/answers", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert "abstention" not in body
    assert "answer" in body and "last_success_at" in body
    assert body["status"] == ("answered" if mode == "ollama" else "degraded")
    assert len(calls) == (1 if mode == "ollama" else 0)
    # The unchanged Gateway must still be able to read ordinary responses.
    AnswerOut.model_validate(body)


def test_plain_no_evidence_response_preserves_required_nulls(payload):
    del payload["abstention"]
    payload["sources"] = []
    payload["last_success_at"] = None
    response = post_request(payload)
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] is None and body["last_success_at"] is None
    assert body["status"] == "insufficient_evidence"
    assert "abstention" not in body


def test_policy_details_cannot_be_attached_to_generated_claims(payload):
    body = post_request(payload).json()
    body.update(status="answered", answer="Use the old form.")
    with pytest.raises(ValidationError):
        AnswerResponse.model_validate(body)
