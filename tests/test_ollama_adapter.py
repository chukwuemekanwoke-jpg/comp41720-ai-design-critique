"""Exercise the API/adapter boundary without requiring a running model."""

import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient
import httpx
import pytest

from answer_service.app import create_app
from answer_service.config import Settings
from answer_service.ollama import PROMPT_VERSION


@pytest.fixture
def payload():
    fixture = Path(__file__).resolve().parents[1] / "data" / "answer_request_demo.json"
    return json.loads(fixture.read_text(encoding="utf-8"))


def answered(**changes):
    return {
        "status": "answered",
        "answer": "A blue form.",
        "checklist": ["Prepare a blue form."],
        "source_indices": [1],
        **changes,
    }


def envelope(output):
    return {
        "model": "llama3.2:3b",
        "message": {"role": "assistant", "content": json.dumps(output)},
        "done": True,
        "done_reason": "stop",
        "eval_count": 25,
    }


def post_with_transport(payload, handler, **settings):
    app = create_app(
        Settings(generation_mode="ollama", **settings),
        transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/answers", json=payload, headers={"X-Request-ID": "ollama-test-1"}
        )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == response.json()["request_id"] == "ollama-test-1"
    return response.json()


def assert_fallback(body, payload):
    assert body["status"] == "degraded"
    assert body["answer"] is None and body["checklist"] == []
    assert body["fallback_used"] is True
    assert body["sources"] == payload["sources"]
    assert body["index_version"] == payload["index_version"]
    assert body["last_success_at"] == payload["last_success_at"]
    assert body["model"] == {"name": "evidence-only", "prompt_version": "none"}


def test_generation_sends_schema_and_maps_only_supplied_citations(payload):
    payload["sources"].append({**payload["sources"][0], "source_id": "SYN002"})

    def handler(request):
        assert request.url.path == "/api/chat"
        outgoing = json.loads(request.content)
        assert outgoing["model"] == "test-model"
        assert outgoing["stream"] is False
        assert "source_indices" in outgoing["format"]["properties"]
        assert outgoing["options"] == {"temperature": 0.2, "num_predict": 128, "num_ctx": 4096}
        supplied = json.loads(outgoing["messages"][1]["content"])
        assert supplied["question"] == payload["question"]
        assert supplied["evidence"][1]["source_index"] == 2
        assert "url" not in supplied["evidence"][1]
        return httpx.Response(200, json={**envelope(answered(source_indices=[2])), "model": "test-model"})

    body = post_with_transport(
        payload, handler, model="test-model", temperature=0.2,
        max_output_tokens=128, context_tokens=4096,
    )
    assert body["status"] == "answered"
    assert body["answer"] == "A blue form."
    assert body["sources"] == [payload["sources"][1]]
    assert body["model"] == {"name": "test-model", "prompt_version": PROMPT_VERSION}
    assert body["fallback_used"] is False
    assert body["index_version"] == payload["index_version"]
    assert body["last_success_at"] == payload["last_success_at"]


def test_valid_model_refusal_is_not_a_transport_failure(payload):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=envelope({
            "status": "insufficient_evidence", "answer": None,
            "checklist": [], "source_indices": [],
        }))

    body = post_with_transport(payload, handler)
    assert body["status"] == "insufficient_evidence"
    assert body["answer"] is None and body["sources"] == []
    assert body["fallback_used"] is False
    assert body["model"]["name"] == "llama3.2:3b"
    assert len(calls) == 1


def test_no_evidence_never_calls_the_model(payload):
    payload["sources"] = []
    payload["last_success_at"] = None

    def handler(request):
        pytest.fail("empty retrieval must not call Ollama")

    body = post_with_transport(payload, handler)
    assert body["status"] == "insufficient_evidence"
    assert body["model"]["name"] == "evidence-only"


@pytest.mark.parametrize("status", [404, 429, 500, 503])
def test_http_failures_preserve_evidence(payload, status):
    body = post_with_transport(payload, lambda request: httpx.Response(status))
    assert_fallback(body, payload)


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadTimeout])
def test_transport_failures_preserve_evidence(payload, error):
    def handler(request):
        raise error("synthetic failure", request=request)

    assert_fallback(post_with_transport(payload, handler), payload)


def test_total_deadline_cancels_slow_generation(payload):
    async def handler(request):
        await asyncio.sleep(0.2)
        return httpx.Response(200, json=envelope(answered()))

    body = post_with_transport(payload, handler, timeout_seconds=0.01)
    assert_fallback(body, payload)


@pytest.mark.parametrize("output", [
    answered(source_indices=[0]),
    answered(source_indices=[2]),
    answered(source_indices=[True]),
    answered(source_indices=[1, 1]),
    answered(source_indices=[]),
    answered(answer=" "),
    answered(answer=None),
    answered(url="https://invented.example.org"),
    answered(checklist=[" "]),
    answered(status="insufficient_evidence"),
])
def test_invalid_claim_structure_or_citations_trigger_fallback(payload, output):
    body = post_with_transport(payload, lambda request: httpx.Response(200, json=envelope(output)))
    assert_fallback(body, payload)


@pytest.mark.parametrize("changes", [
    {"done": False},
    {"done_reason": "length"},
    {"message": {"role": "assistant", "content": "not json"}},
    {"message": {"role": "user", "content": "{}"}},
])
def test_unusable_envelopes_trigger_fallback(payload, changes):
    body = post_with_transport(
        payload, lambda request: httpx.Response(200, json={**envelope(answered()), **changes})
    )
    assert_fallback(body, payload)


def test_invalid_outer_json_triggers_fallback(payload):
    assert_fallback(post_with_transport(payload, lambda request: httpx.Response(200, text="{")), payload)


def test_input_budget_returns_evidence_without_silently_truncating_it(payload):
    def handler(request):
        pytest.fail("over-budget input must not be submitted to the model")

    assert_fallback(post_with_transport(payload, handler, max_input_characters=10), payload)


@pytest.mark.parametrize("setting", [
    {"generation_mode": "unknown"},
    {"timeout_seconds": 0},
    {"timeout_seconds": float("nan")},
    {"max_output_tokens": -1},
    {"ollama_url": "file:///tmp/model"},
    {"ollama_url": "http://user:password@localhost:11434"},
])
def test_invalid_configuration_fails_at_startup(setting):
    with pytest.raises(ValueError):
        Settings(**setting)


def test_environment_can_enable_a_different_model(monkeypatch):
    monkeypatch.setenv("ANSWER_GENERATION_MODE", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "another-model")
    config = Settings.from_env()
    assert config.generation_mode == "ollama"
    assert config.model == "another-model"
