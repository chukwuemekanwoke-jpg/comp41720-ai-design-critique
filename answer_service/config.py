"""Process configuration; defaults preserve the offline evidence-only API."""

import os
from dataclasses import dataclass
from math import isfinite
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    generation_mode: str = "evidence_only"
    ollama_url: str = "http://127.0.0.1:11434"
    model: str = "llama3.2:3b"
    timeout_seconds: float = 20.0
    temperature: float = 0.0
    max_output_tokens: int = 256
    context_tokens: int = 8192
    max_input_characters: int = 8000

    def __post_init__(self):
        if self.generation_mode not in {"evidence_only", "ollama"}:
            raise ValueError("ANSWER_GENERATION_MODE must be evidence_only or ollama")
        url = urlsplit(self.ollama_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
        ):
            raise ValueError(
                "OLLAMA_BASE_URL must be an HTTP(S) origin without credentials"
            )
        if not self.model.strip() or len(self.model) > 256:
            raise ValueError("OLLAMA_MODEL must contain 1-256 characters")
        if not isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 120:
            raise ValueError(
                "OLLAMA_TIMEOUT_SECONDS must be between 0 (exclusive) and 120"
            )
        if not isfinite(self.temperature) or not 0 <= self.temperature <= 2:
            raise ValueError("OLLAMA_TEMPERATURE must be between 0 and 2")
        if not 32 <= self.max_output_tokens <= 2048:
            raise ValueError("OLLAMA_MAX_OUTPUT_TOKENS must be between 32 and 2048")
        if not 2048 <= self.context_tokens <= 32768:
            raise ValueError("OLLAMA_CONTEXT_TOKENS must be between 2048 and 32768")
        if self.max_output_tokens >= self.context_tokens:
            raise ValueError("output token cap must be smaller than context size")
        if not 1 <= self.max_input_characters <= 40000:
            raise ValueError("ANSWER_MAX_INPUT_CHARACTERS must be between 1 and 40000")

    @classmethod
    def from_env(cls):
        return cls(
            generation_mode=os.getenv("ANSWER_GENERATION_MODE", "evidence_only"),
            ollama_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            model=os.getenv("OLLAMA_MODEL", "llama3.2:3b"),
            timeout_seconds=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "20")),
            temperature=float(os.getenv("OLLAMA_TEMPERATURE", "0")),
            max_output_tokens=int(os.getenv("OLLAMA_MAX_OUTPUT_TOKENS", "256")),
            context_tokens=int(os.getenv("OLLAMA_CONTEXT_TOKENS", "8192")),
            max_input_characters=int(os.getenv("ANSWER_MAX_INPUT_CHARACTERS", "8000")),
        )
