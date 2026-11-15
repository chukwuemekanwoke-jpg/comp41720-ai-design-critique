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
    model_serializer,
)

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=256)]
HTTP_URL = TypeAdapter(HttpUrl)
NOTICE = "Information only. This is not an eligibility decision or legal advice."
PENDING_UPDATE_MESSAGE = (
    "One or more sources used for this question have changed and the saved "
    "information has not been updated yet. Check the linked official sources "
    "or try again shortly."
)


def validate_aware_timestamp(value: str) -> str:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value


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


class PendingSource(ContractModel):
    """Version facts supplied by Gateway; no source polling happens here."""

    source_id: Identifier
    indexed_source_version: int = Field(gt=0)
    latest_source_version: int = Field(gt=0)
    detected_at: str | None = Field(max_length=64)

    @field_validator("source_id")
    @classmethod
    def reject_blank_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must contain non-whitespace text")
        return value

    @field_validator("detected_at")
    @classmethod
    def require_aware_detection_time(cls, value: str | None) -> str | None:
        return validate_aware_timestamp(value) if value is not None else None

    @model_validator(mode="after")
    def require_newer_source_version(self) -> Self:
        if self.latest_source_version <= self.indexed_source_version:
            raise ValueError("latest_source_version must be newer than indexed_source_version")
        return self


class AbstentionDecision(ContractModel):
    reason: Literal["pending_source_update"]
    affected_sources: list[PendingSource] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def require_unique_sources(self) -> Self:
        identifiers = [source.source_id for source in self.affected_sources]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("affected_sources must not contain duplicate source IDs")
        return self


class AffectedSourceDetail(PendingSource):
    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def require_http_url(cls, value: str) -> str:
        if any(character.isspace() for character in value):
            raise ValueError("must not contain whitespace")
        HTTP_URL.validate_python(value)
        return value


class AbstentionResponse(ContractModel):
    reason: Literal["pending_source_update"]
    message: Literal[PENDING_UPDATE_MESSAGE] = PENDING_UPDATE_MESSAGE
    affected_sources: list[AffectedSourceDetail] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def require_unique_sources(self) -> Self:
        identifiers = [source.source_id for source in self.affected_sources]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("affected_sources must not contain duplicate source IDs")
        return self


class AnswerRequest(ContractModel):
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)
    ]
    sources: list[SourceEvidence] = Field(max_length=10)
    index_version: Identifier
    last_success_at: str | None = None
    abstention: AbstentionDecision | None = None

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
        return validate_aware_timestamp(value)

    @model_validator(mode="after")
    def require_evidence_freshness(self) -> Self:
        if self.sources and self.last_success_at is None:
            raise ValueError("last_success_at is required when sources are supplied")
        if self.abstention is not None:
            for affected in self.abstention.affected_sources:
                evidence = [s for s in self.sources if s.source_id == affected.source_id]
                if not evidence:
                    raise ValueError("affected source must occur in supplied evidence")
                if any(s.source_version != affected.indexed_source_version for s in evidence):
                    raise ValueError("indexed source version must match all its supplied passages")
                if len({s.url for s in evidence}) != 1:
                    raise ValueError("affected source must have one canonical URL")
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
    abstention: AbstentionResponse | None = None

    @model_validator(mode="after")
    def require_coherent_policy_refusal(self) -> Self:
        if self.abstention is not None and (
            self.status != "insufficient_evidence"
            or self.answer is not None
            or self.checklist
            or self.sources
            or self.fallback_used
            or self.model.name != "policy-response"
            or self.model.prompt_version != "none"
        ):
            raise ValueError("pending-update responses must be policy refusals without claims")
        return self

    @model_serializer(mode="wrap")
    def omit_unused_abstention(self, handler):
        # Preserve every legacy field, including required null answer/freshness.
        body = handler(self)
        if self.abstention is None:
            body.pop("abstention", None)
        return body


class ErrorResponse(ContractModel):
    request_id: str
    error: Literal["invalid_request"]
    message: str
