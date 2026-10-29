"""Gateway-only settings; downstream credentials and models stay in their services."""
import os
from dataclasses import dataclass
from math import isfinite
from urllib.parse import urlsplit


def origin(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise ValueError("Use an HTTP(S) origin without credentials, path, query or fragment")
    # Reading port also detects malformed ports.
    parsed.port
    return value.rstrip("/")


@dataclass(frozen=True)
class Settings:
    retrieval_url: str = "http://127.0.0.1:8002"
    answer_url: str = "http://127.0.0.1:8003"
    retrieval_timeout: float = 3.0
    answer_timeout: float = 23.0
    total_timeout: float = 30.0
    cors_origins: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "retrieval_url", origin(self.retrieval_url))
        object.__setattr__(self, "answer_url", origin(self.answer_url))
        object.__setattr__(self, "cors_origins", tuple(origin(value) for value in self.cors_origins))
        for value in (self.retrieval_timeout, self.answer_timeout, self.total_timeout):
            if not isfinite(value) or not 0 < value <= 120:
                raise ValueError("Gateway deadlines must be finite, positive and at most 120 seconds")
        if max(self.retrieval_timeout, self.answer_timeout) > self.total_timeout:
            raise ValueError("A downstream deadline cannot exceed the total deadline")

    @classmethod
    def from_env(cls):
        return cls(
            retrieval_url=os.getenv("RETRIEVAL_BASE_URL", "http://127.0.0.1:8002"),
            answer_url=os.getenv("ANSWER_BASE_URL", "http://127.0.0.1:8003"),
            retrieval_timeout=float(os.getenv("GATEWAY_RETRIEVAL_TIMEOUT_SECONDS", "3")),
            answer_timeout=float(os.getenv("GATEWAY_ANSWER_TIMEOUT_SECONDS", "23")),
            total_timeout=float(os.getenv("GATEWAY_TOTAL_TIMEOUT_SECONDS", "30")),
            cors_origins=tuple(value.strip().rstrip("/") for value in
                               os.getenv("GATEWAY_CORS_ORIGINS", "").split(",") if value.strip()),
        )
