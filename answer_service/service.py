"""Choose generated, insufficient-evidence or evidence-only responses."""

import logging

from answer_service.models import AnswerRequest, AnswerResponse, ModelInfo
from answer_service.ollama import GenerationFailure, OllamaAdapter, PROMPT_VERSION


logger = logging.getLogger(__name__)


async def build_answer(
    payload: AnswerRequest, request_id: str, generator: OllamaAdapter | None
) -> AnswerResponse:
    has_evidence = bool(payload.sources)
    if has_evidence and generator is not None:
        try:
            generated = await generator.generate(payload)
        except GenerationFailure:
            # Do not log raw evidence, model output or connection details.
            logger.warning("Ollama generation failed; returning evidence-only fallback")
        else:
            output = generated.output
            return AnswerResponse(
                request_id=request_id,
                status=output.status,
                answer=output.answer,
                checklist=output.checklist,
                sources=[payload.sources[index - 1] for index in output.source_indices],
                index_version=payload.index_version,
                last_success_at=payload.last_success_at,
                fallback_used=False,
                model=ModelInfo(name=generated.model, prompt_version=PROMPT_VERSION),
            )
    return AnswerResponse(
        request_id=request_id,
        status="degraded" if has_evidence else "insufficient_evidence",
        answer=None,
        checklist=[],
        sources=payload.sources,
        index_version=payload.index_version,
        last_success_at=payload.last_success_at,
        fallback_used=has_evidence,
        model=ModelInfo(name="evidence-only", prompt_version="none"),
    )
