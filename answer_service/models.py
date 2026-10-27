"""Validated messages exchanged between the gateway and Answer Service."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=256)]
HTTP_URL = TypeAdapter(HttpUrl)
NOTICE = "Information only. This is not an eligibility decision or legal advice."


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SourceEvidence(ContractModel):
    source_id: Identifier
    snapshot_id: Identifier
    source_version: int = Field(gt=0)
    url: str = Field(min_length=1, max_length=2048)
    passage: str = Field(min_length=1, max_length=4000)

    @field_validator("source_id", "snapshot_id", "passage")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must contain non-whitespace text")
        # Preserve original evidence rather than silently changing its content.
        return value

    @field_validator("url")
    @classmethod
    def require_http_url(cls, value: str) -> str:
        if any(character.isspace() for character in value):
            raise ValueError("must not contain whitespace")
        HTTP_URL.validate_python(value)
        return value


class AnswerRequest(ContractModel):
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)
    ]
    sources: list[SourceEvidence] = Field(max_length=10)
    index_version: Identifier
    last_success_at: str | None = None

    @field_validator("index_version")
    @classmethod
    def reject_blank_version(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must contain non-whitespace text")
        return value

    @field_validator("last_success_at")
    @classmethod
    def require_aware_timestamp(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if len(value) > 64:
            raise ValueError("timestamp must be at most 64 characters")
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def require_evidence_freshness(self) -> Self:
        if self.sources and self.last_success_at is None:
            raise ValueError("last_success_at is required when sources are supplied")
        return self


class ModelInfo(ContractModel):
    name: str
    prompt_version: str


class AnswerResponse(ContractModel):
    request_id: str
    status: Literal["answered", "degraded", "insufficient_evidence"]
    answer: str | None
    checklist: list[str]
    sources: list[SourceEvidence]
    index_version: str
    last_success_at: str | None
    fallback_used: bool
    model: ModelInfo
    notice: str = NOTICE


class ErrorResponse(ContractModel):
    request_id: str
    error: Literal["invalid_request"]
    message: str
