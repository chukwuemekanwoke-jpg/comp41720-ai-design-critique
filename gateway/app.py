"""Public REST Gateway: retrieve pinned evidence, then request a grounded answer."""
import asyncio
import re
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from .client import UpstreamFailure, orchestrate, retrieve
from .config import Settings
from .models import AnswerOut, ErrorOut, QuestionIn

REQUEST_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def create_app(settings=None, *, retrieval_transport=None, answer_transport=None):
    config = settings if settings is not None else Settings.from_env()

    @asynccontextmanager
    async def lifespan(application):
        async with httpx.AsyncClient(
            base_url=config.retrieval_url.rstrip("/"), timeout=config.retrieval_timeout,
            transport=retrieval_transport, trust_env=False, follow_redirects=False,
        ) as retrieval_client, httpx.AsyncClient(
            base_url=config.answer_url.rstrip("/"), timeout=config.answer_timeout,
            transport=answer_transport, trust_env=False, follow_redirects=False,
        ) as answer_client:
            application.state.retrieval = retrieval_client
            application.state.answer = answer_client
            yield

    service = FastAPI(title="StudentPath Gateway", version="0.2.0", lifespan=lifespan)
    requests = defaultdict(int)
    duration_sum = defaultdict(float)
    duration_count = defaultdict(int)

    @service.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        request.state.request_id = incoming if REQUEST_ID_RE.fullmatch(incoming) else uuid.uuid4().hex
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = route.path if route else "unmatched"
        requests[(path, response.status_code)] += 1
        duration_sum[path] += time.perf_counter() - started
        duration_count[path] += 1
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @service.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc):
        return JSONResponse(status_code=400, content=ErrorOut(
            request_id=request.state.request_id, error="invalid_request",
            message="Send only a question containing 3 to 500 characters."
        ).model_dump())

    @service.exception_handler(Exception)
    async def internal_error(request: Request, exc):
        request_id = getattr(request.state, "request_id", uuid.uuid4().hex)
        return JSONResponse(status_code=500, headers={"X-Request-ID": request_id}, content=ErrorOut(
            request_id=request_id, error="internal_error", message="The request could not be completed."
        ).model_dump())

    @service.post("/v1/questions", response_model=AnswerOut, responses={
        400: {"model": ErrorOut}, 502: {"model": ErrorOut}, 504: {"model": ErrorOut}})
    async def ask(payload: QuestionIn, request: Request):
        try:
            return await orchestrate(service.state.retrieval, service.state.answer, config,
                                     request.state.request_id, payload.question)
        except UpstreamFailure as exc:
            return JSONResponse(status_code=504 if exc.timed_out else 502, content=ErrorOut(
                request_id=request.state.request_id,
                error="upstream_timeout" if exc.timed_out else "upstream_unavailable",
                message="A downstream deadline expired." if exc.timed_out else "A downstream service is unavailable or returned invalid evidence."
            ).model_dump())

    @service.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @service.get("/readyz")
    async def readyz():
        async def retrieval_ready():
            # Liveness alone does not establish a readable committed index.
            await retrieve(service.state.retrieval, uuid.uuid4().hex, "readiness probe", config.retrieval_timeout)

        async def answer_ready():
            async with asyncio.timeout(config.retrieval_timeout):
                response = await service.state.answer.get("/healthz")
                if response.status_code != 200 or response.json() != {"status": "ok"}:
                    raise UpstreamFailure()

        outcomes = await asyncio.gather(retrieval_ready(), answer_ready(), return_exceptions=True)
        dependencies = {name: "unavailable" if isinstance(outcome, BaseException) else "ready"
                        for name, outcome in zip(("retrieval_api", "answer_service"), outcomes)}
        ready = all(value == "ready" for value in dependencies.values())
        return JSONResponse(status_code=200 if ready else 503,
                            content={"status": "ready" if ready else "not_ready", "dependencies": dependencies})

    @service.get("/metrics", response_class=PlainTextResponse)
    def metrics():
        lines = ["# TYPE gateway_requests_total counter"]
        for (path, status), count in sorted(requests.items()):
            lines.append(f'gateway_requests_total{{path="{path}",status="{status}"}} {count}')
        lines.append("# TYPE gateway_request_duration_seconds summary")
        for path in sorted(duration_count):
            lines.append(f'gateway_request_duration_seconds_sum{{path="{path}"}} {duration_sum[path]:.6f}')
            lines.append(f'gateway_request_duration_seconds_count{{path="{path}"}} {duration_count[path]}')
        return "\n".join(lines) + "\n"

    # Outermost CORS also decorates safe 500 responses; exact origins only.
    if config.cors_origins:
        return CORSMiddleware(
            service, allow_origins=list(config.cors_origins), allow_credentials=False,
            allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        )
    return service


app = create_app()
