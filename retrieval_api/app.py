"""FastAPI retrieval endpoint with injectable storage and pinned evidence."""
import re
import os
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .freshness import SourceStatusCache, assess
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


class PendingSourceOut(BaseModel):
    source_id: str
    indexed_source_version: int
    latest_source_version: int
    detected_at: str | None


class RetrieveOut(BaseModel):
    request_id: str
    index_version: str
    last_success_at: datetime
    passages: list[PassageOut]
    # ADR-0003: sources among the returned passages with a detected, unindexed change.
    pending_sources: list[PendingSourceOut]
    # False when any returned source's Collector status is missing or too old.
    freshness_confirmed: bool


class ErrorOut(BaseModel):
    request_id: str
    error: Literal["invalid_request", "index_version_not_found", "index_unavailable"]
    message: str


def create_app(repository: PassageRepository | None = None,
               status_cache: SourceStatusCache | None = None, lifespan=None) -> FastAPI:
    """Without an adapter, fail closed with 503; never serve demo data implicitly.

    Without a status cache, freshness is never confirmed and nothing is pending.
    """
    service = FastAPI(title="StudentPath Retrieval API", version="0.2.0", lifespan=lifespan)

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
        ranked = rank(snapshot, payload.question, payload.top_k)
        # TODO(ADR-0003): apply the calibrated retrieval-score threshold before this
        # check. The keyword ranker returns any passage sharing one word with the
        # question, so a weakly related changed page can make a question abstain.
        freshness = assess((passage for passage, _ in ranked), status_cache)
        return RetrieveOut(
            request_id=payload.request_id, index_version=snapshot.index_version,
            last_success_at=snapshot.last_success_at,
            passages=[PassageOut(**vars(passage), score=score) for passage, score in ranked],
            pending_sources=[PendingSourceOut(**vars(p)) for p in freshness.pending],
            freshness_confirmed=freshness.confirmed,
        )

    @service.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return service


def create_demo_app() -> FastAPI:
    from .demo import demo_repository
    return create_app(demo_repository())


def create_configured_app() -> FastAPI:
    path = os.getenv("RETRIEVAL_INDEX_DB")
    if not path:
        return create_app()
    from .sqlite_repository import SQLitePassageRepository
    repository = SQLitePassageRepository(path)
    collector_url = os.getenv("COLLECTOR_BASE_URL")
    if not collector_url:
        return create_app(repository)

    from .freshness import CollectorStatusClient, StatusPoller
    cache = SourceStatusCache()

    @asynccontextmanager
    async def poll_collector(_application):
        client = CollectorStatusClient(collector_url)
        poller = StatusPoller(cache, client.fetch,
                              lambda: sorted({p.source_id for p in repository.pin().passages}))
        stop = threading.Event()
        thread = threading.Thread(target=poller.run, args=(stop,), daemon=True, name="status-poller")
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=5)
            client.close()

    return create_app(repository, cache, lifespan=poll_collector)


app = create_configured_app()
