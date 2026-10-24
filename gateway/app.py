"""Placeholder gateway API for StudentPath.

This stub fixes the public contract (paths, request id, response shape, status
vocabulary, error shape, metrics) so the other services and the evaluation
harness can be written against it. It returns canned data and calls no other
service. Replace the body of `ask` with real calls to the retrieval API and the
answer service once those exist; keep the models and paths stable.

Test hooks (stub only): a question containing "[missing]" returns the
insufficient-evidence shape, and one containing "[degraded]" returns the
fallback shape.
"""
from __future__ import annotations

import re
import time
import uuid
from collections import defaultdict
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

API_VERSION = "v1"
INDEX_VERSION = "stub-0"
NOTICE = "Information only. This is not an eligibility decision or legal advice."
REQUEST_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


class QuestionIn(BaseModel):
    question: str = Field(min_length=3, max_length=500, examples=[
        "Where are the requirements for moving from Stamp 2 to graduate Stamp 1G?"])


class Source(BaseModel):
    source_id: str
    snapshot_id: str
    source_version: int
    url: str
    passage: str


class ModelInfo(BaseModel):
    name: str
    prompt_version: str


class AnswerOut(BaseModel):
    request_id: str
    status: Literal["answered", "insufficient_evidence", "degraded"]
    answer: str | None
    checklist: list[str]
    sources: list[Source]
    index_version: str
    last_success_at: str | None
    fallback_used: bool
    model: ModelInfo
    notice: str
    stub: bool = True


class ErrorOut(BaseModel):
    request_id: str
    error: Literal["invalid_request", "upstream_unavailable", "upstream_timeout", "internal_error"]
    message: str


app = FastAPI(title="StudentPath Gateway (placeholder)", version="0.0.1")

_requests: dict[tuple[str, int], int] = defaultdict(int)
_duration_sum: dict[str, float] = defaultdict(float)
_duration_count: dict[str, int] = defaultdict(int)


@app.middleware("http")
async def request_context(request: Request, call_next):
    incoming = request.headers.get("x-request-id", "")
    request.state.request_id = incoming if REQUEST_ID_RE.fullmatch(incoming) else uuid.uuid4().hex
    started = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    path = route.path if route else "unmatched"
    _requests[(path, response.status_code)] += 1
    _duration_sum[path] += time.perf_counter() - started
    _duration_count[path] += 1
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError):
    body = ErrorOut(request_id=request.state.request_id, error="invalid_request",
                    message="Send a JSON body with a question of 3 to 500 characters.")
    return JSONResponse(status_code=400, content=body.model_dump())


@app.post(f"/{API_VERSION}/questions", response_model=AnswerOut,
          responses={400: {"model": ErrorOut}, 502: {"model": ErrorOut}, 504: {"model": ErrorOut}})
def ask(payload: QuestionIn, request: Request) -> AnswerOut:
    request_id = request.state.request_id
    question = payload.question
    model = ModelInfo(name="stub-model", prompt_version="stub-0")
    if "[missing]" in question:
        return AnswerOut(request_id=request_id, status="insufficient_evidence", answer=None,
                         checklist=[], sources=[], index_version=INDEX_VERSION,
                         last_success_at=None, fallback_used=False, model=model, notice=NOTICE)
    degraded = "[degraded]" in question
    source = Source(source_id="S000", snapshot_id="S000:stub", source_version=1,
                    url="https://www.irishimmigration.ie/",
                    passage="[stub] Placeholder passage. Not real guidance.")
    return AnswerOut(
        request_id=request_id,
        status="degraded" if degraded else "answered",
        answer=None if degraded else "[stub] Placeholder answer. The retrieval and answer services are not connected yet.",
        checklist=["[stub] Placeholder checklist item"],
        sources=[source],
        index_version=INDEX_VERSION,
        last_success_at="2026-01-01T00:00:00+00:00",
        fallback_used=degraded,
        model=ModelInfo(name="local-fallback", prompt_version="stub-0") if degraded else model,
        notice=NOTICE,
    )


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict:
    # Placeholder: report real dependency checks (retrieval API, answer service) here.
    return {"status": "ready", "dependencies": {"retrieval_api": "not_connected", "answer_service": "not_connected"}}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    lines = ["# TYPE gateway_requests_total counter"]
    for (path, status), count in sorted(_requests.items()):
        lines.append(f'gateway_requests_total{{path="{path}",status="{status}"}} {count}')
    lines.append("# TYPE gateway_request_duration_seconds summary")
    for path in sorted(_duration_count):
        lines.append(f'gateway_request_duration_seconds_sum{{path="{path}"}} {_duration_sum[path]:.6f}')
        lines.append(f'gateway_request_duration_seconds_count{{path="{path}"}} {_duration_count[path]}')
    return "\n".join(lines) + "\n"
