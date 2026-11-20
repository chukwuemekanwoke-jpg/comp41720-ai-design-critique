"""Answer API with opt-in Ollama generation and an offline evidence fallback."""

import re
import uuid
from time import perf_counter
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from answer_service.metrics import AnswerMetrics

from answer_service.config import Settings
from answer_service.models import AnswerRequest, AnswerResponse, ErrorResponse
from answer_service.ollama import OllamaAdapter
from answer_service.service import build_answer

REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")


def create_app(
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    metrics = AnswerMetrics()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        config = settings if settings is not None else Settings.from_env()
        application.state.generator = None
        if config.generation_mode == "ollama":
            async with httpx.AsyncClient(
                base_url=config.ollama_url,
                timeout=config.timeout_seconds,
                transport=transport,
                trust_env=False,
            ) as client:
                application.state.generator = OllamaAdapter(config, client, metrics=metrics)
                yield
        else:
            yield

    application = FastAPI(
        title="StudentPath Answer Service", version="0.2.0", lifespan=lifespan
    )

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("X-Request-ID", "")
        request.state.request_id = (
            incoming if REQUEST_ID_PATTERN.fullmatch(incoming) else uuid.uuid4().hex
        )
        measured = request.method == "POST" and request.url.path == "/v1/answers"
        started = perf_counter()
        status_class = "5xx"
        try:
            response = await call_next(request)
            status_class = f"{response.status_code // 100}xx"
        finally:
            if measured:
                metrics.requests.labels(status_class=status_class).inc()
                metrics.duration.observe(perf_counter() - started)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Report field locations without logging or echoing the evidence itself.
        fields = [
            ".".join(str(part) for part in error["loc"]) for error in exc.errors()[:4]
        ]
        body = ErrorResponse(
            request_id=request.state.request_id,
            error="invalid_request",
            message="Invalid answer request. Check: " + ", ".join(fields) + ".",
        )
        return JSONResponse(status_code=400, content=body.model_dump())

    @application.post(
        "/v1/answers",
        response_model=AnswerResponse,
        responses={400: {"model": ErrorResponse}},
        summary="Answer from supplied evidence, or return a labelled fallback",
    )
    async def answer(payload: AnswerRequest, request: Request) -> AnswerResponse:
        result = await build_answer(
            payload, request.state.request_id, request.app.state.generator
        )
        metrics.responses.labels(status=result.status).inc()
        return result

    @application.get("/metrics", include_in_schema=False)
    def exported_metrics() -> Response:
        return Response(generate_latest(metrics.registry), headers={"Content-Type": CONTENT_TYPE_LATEST})

    @application.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
