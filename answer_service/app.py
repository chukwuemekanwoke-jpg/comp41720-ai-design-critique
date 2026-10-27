"""Evidence-only API milestone; no generation model is called yet."""

import re
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from answer_service.models import (
    AnswerRequest,
    AnswerResponse,
    ErrorResponse,
    ModelInfo,
)

REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")

app = FastAPI(
    title="StudentPath Answer Service",
    version="0.1.0",
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    incoming = request.headers.get("X-Request-ID", "")
    request.state.request_id = (
        incoming if REQUEST_ID_PATTERN.fullmatch(incoming) else uuid.uuid4().hex
    )
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError):
    # Include field locations, without echoing evidence or raw request contents.
    fields = [
        ".".join(str(part) for part in error["loc"]) for error in exc.errors()[:4]
    ]
    body = ErrorResponse(
        request_id=request.state.request_id,
        error="invalid_request",
        message="Invalid answer request. Check: " + ", ".join(fields) + ".",
    )
    return JSONResponse(status_code=400, content=body.model_dump())


@app.post(
    "/v1/answers",
    response_model=AnswerResponse,
    responses={400: {"model": ErrorResponse}},
    summary="Return supplied evidence without generating new claims",
)
def answer(payload: AnswerRequest, request: Request) -> AnswerResponse:
    has_evidence = bool(payload.sources)
    return AnswerResponse(
        request_id=request.state.request_id,
        status="degraded" if has_evidence else "insufficient_evidence",
        answer=None,
        checklist=[],
        sources=payload.sources,
        index_version=payload.index_version,
        last_success_at=payload.last_success_at,
        fallback_used=has_evidence,
        model=ModelInfo(name="evidence-only", prompt_version="none"),
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
