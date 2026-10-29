"""Opt-in actual HTTP calls to local Ollama through the Answer Service."""

import json
import os
from pathlib import Path
import time

from fastapi.testclient import TestClient
import pytest

from answer_service.app import create_app
from answer_service.config import Settings


pytestmark = pytest.mark.skipif(
    os.getenv("OLLAMA_INTEGRATION") != "1",
    reason="Set OLLAMA_INTEGRATION=1 to call an installed local model",
)


@pytest.mark.parametrize("scenario", ["supported", "unrelated", "missing_model"])
def test_real_ollama_via_answer_service(scenario):
    path = Path(__file__).resolve().parents[1] / "data" / "answer_request_demo.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    if scenario == "unrelated":
        payload["sources"][0]["passage"] = "The fictional office opens at 9am."
    if scenario == "missing_model":
        # A nonexistent local tag must fail without downloading anything.
        model = "studentpath-deliberately-missing-test-model:unavailable"
    config = Settings(
        generation_mode="ollama",
        model=model,
        ollama_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
    )
    started = time.perf_counter()
    with TestClient(create_app(config)) as client:
        response = client.post("/v1/answers", json=payload)
    duration = time.perf_counter() - started
    body = response.json()
    print(json.dumps({
        "scenario": scenario, "seconds": round(duration, 3),
        "status": body.get("status"), "answer": body.get("answer"),
        "checklist": body.get("checklist"), "model": body.get("model"),
    }))
    assert response.status_code == 200
    if scenario == "supported":
        assert body["status"] == "answered"
        assert "blue" in body["answer"].lower() and "form" in body["answer"].lower()
        assert body["sources"] == payload["sources"]
        assert body["fallback_used"] is False
    elif scenario == "unrelated":
        assert body["status"] == "insufficient_evidence"
        assert body["answer"] is None and body["sources"] == []
        assert body["fallback_used"] is False
    else:
        assert body["status"] == "degraded"
        assert body["answer"] is None
        assert body["sources"] == payload["sources"]
        assert body["fallback_used"] is True
    assert body["index_version"] == payload["index_version"]
    assert body["last_success_at"] == payload["last_success_at"]
