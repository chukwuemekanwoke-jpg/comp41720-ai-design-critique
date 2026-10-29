"""Validate the HTTP boundary without importing another service's implementation."""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, TypeAdapter, field_validator, model_validator

NOTICE = "Information only. This is not an eligibility decision or legal advice."
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=256)]


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone")
    return parsed


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class QuestionIn(ContractModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class Source(ContractModel):
    source_id: Identifier
    snapshot_id: Identifier
    source_version: int = Field(gt=0)
    url: str = Field(min_length=1, max_length=2048)
    passage: str = Field(min_length=1, max_length=4000)

    @field_validator("source_id", "snapshot_id", "passage")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Must not be blank")
        return value

    @field_validator("url")
    @classmethod
    def valid_url(cls, value):
        if any(c.isspace() for c in value):
            raise ValueError("Whitespace is not valid in a URL")
        TypeAdapter(HttpUrl).validate_python(value)
        return value


class Passage(ContractModel):
    passage_id: Identifier
    source_id: Identifier
    snapshot_id: Identifier
    source_version: int
    url: str
    text: str
    score: float = Field(ge=0, le=1, allow_inf_nan=False)

    def as_source(self):
        return Source(source_id=self.source_id, snapshot_id=self.snapshot_id,
                      source_version=self.source_version, url=self.url, passage=self.text)


class RetrievalOut(ContractModel):
    request_id: str
    index_version: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    last_success_at: str = Field(max_length=64)
    passages: list[Passage] = Field(max_length=5)

    @field_validator("last_success_at")
    @classmethod
    def aware_timestamp(cls, value):
        timestamp(value)
        return value

    @field_validator("index_version")
    @classmethod
    def nonblank_version(cls, value):
        if not value.strip():
            raise ValueError("Index version is blank")
        return value

    @model_validator(mode="after")
    def unique_passages(self):
        if len({p.passage_id for p in self.passages}) != len(self.passages):
            raise ValueError("Duplicate passage identifiers")
        return self


class ModelInfo(ContractModel):
    name: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)


class AnswerOut(ContractModel):
    request_id: str
    status: Literal["answered", "insufficient_evidence", "degraded"]
    answer: str | None
    checklist: list[str]
    sources: list[Source] = Field(max_length=10)
    index_version: str
    last_success_at: str | None
    fallback_used: bool
    model: ModelInfo
    notice: str = NOTICE

    @model_validator(mode="after")
    def coherent_status(self):
        if self.notice != NOTICE:
            raise ValueError("Unexpected notice")
        if self.last_success_at is not None:
            timestamp(self.last_success_at)
        if self.status == "answered":
            if not self.answer or not self.answer.strip() or not self.sources or self.fallback_used:
                raise ValueError("Invalid answered response")
        elif self.answer is not None or self.checklist:
            raise ValueError("Non-answers cannot include claims or checklist items")
        elif self.status == "insufficient_evidence":
            if self.sources or self.fallback_used:
                raise ValueError("Refusal cannot include sources or mark fallback")
        elif not self.sources or not self.fallback_used:
            raise ValueError("Degraded response must retain evidence and mark fallback")
        if self.sources and self.last_success_at is None:
            raise ValueError("Evidence requires freshness")
        return self


class ErrorOut(ContractModel):
    request_id: str
    error: Literal["invalid_request", "upstream_unavailable", "upstream_timeout", "internal_error"]
    message: str
