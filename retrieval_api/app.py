"""FastAPI retrieval endpoint with injectable storage and pinned evidence."""
import re
import uuid
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .repository import IndexUnavailable, IndexVersionNotFound, PassageRepository
from .search import rank

REQUEST_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


class RetrieveIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    question: str = Field(min_length=3, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20, strict=True)
    index_version: str | None = Field(default=None, min_length=1, max_length=128)


class PassageOut(BaseModel):
    passage_id: str
    source_id: str
    snapshot_id: str
    source_version: int
    url: str
    text: str
    score: float = Field(ge=0, le=1)


class RetrieveOut(BaseModel):
    request_id: str
    index_version: str
    last_success_at: datetime
    passages: list[PassageOut]


class ErrorOut(BaseModel):
    request_id: str
    error: Literal["invalid_request", "index_version_not_found", "index_unavailable"]
    message: str


def create_app(repository: PassageRepository | None = None) -> FastAPI:
    """Without an adapter, fail closed with 503; never serve demo data implicitly."""
    service = FastAPI(title="StudentPath Retrieval API", version="0.1.0")

    @service.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        request.state.request_id = incoming if REQUEST_ID_RE.fullmatch(incoming) else uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @service.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Preserve a valid body ID even when another field fails validation.
        body_id = exc.body.get("request_id") if isinstance(exc.body, dict) else None
        if isinstance(body_id, str) and REQUEST_ID_RE.fullmatch(body_id):
            request.state.request_id = body_id
        return JSONResponse(status_code=400, content=ErrorOut(
            request_id=request.state.request_id, error="invalid_request",
            message="Send request_id, question (3-500 characters), top_k (1-20), and optional index_version."
        ).model_dump())

    @service.post("/v1/retrieve", response_model=RetrieveOut, responses={
        400: {"model": ErrorOut}, 404: {"model": ErrorOut}, 503: {"model": ErrorOut}})
    def retrieve(payload: RetrieveIn, request: Request):
        request.state.request_id = payload.request_id
        try:
            if repository is None:
                raise IndexUnavailable()
            snapshot = repository.pin(payload.index_version)
        except (IndexVersionNotFound, IndexUnavailable) as exc:
            missing = isinstance(exc, IndexVersionNotFound)
            return JSONResponse(status_code=404 if missing else 503, content=ErrorOut(
                request_id=payload.request_id,
                error="index_version_not_found" if missing else "index_unavailable",
                message="Requested index version is not retained." if missing else "No readable committed index is available."
            ).model_dump())
        return RetrieveOut(
            request_id=payload.request_id, index_version=snapshot.index_version,
            last_success_at=snapshot.last_success_at,
            passages=[PassageOut(**vars(passage), score=score)
                      for passage, score in rank(snapshot, payload.question, payload.top_k)],
        )

    @service.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return service


def create_demo_app() -> FastAPI:
    from .demo import demo_repository
    return create_app(demo_repository())


app = create_app()
