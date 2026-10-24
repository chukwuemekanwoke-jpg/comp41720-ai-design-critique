from __future__ import annotations

from dataclasses import dataclass
import hashlib


@dataclass(frozen=True, slots=True)
class Passage:
    passage_id: str
    snapshot_id: str
    chunk_index: int
    text: str
    content_sha256: str
    chunker_version: str


class DeterministicChunker:
    """
    Split snapshot text into repeatable overlapping word windows.

    The same snapshot and chunker version always produce the same
    passage IDs. source_version is deliberately not included, allowing
    A -> B -> A to reuse A's existing passages.
    """

    def __init__(
        self,
        max_words: int = 120,
        overlap_words: int = 20,
        version: str = "word-window-v1",
    ) -> None:
        if max_words <= 0:
            raise ValueError("max_words must be positive")

        if overlap_words < 0:
            raise ValueError("overlap_words cannot be negative")

        if overlap_words >= max_words:
            raise ValueError(
                "overlap_words must be smaller than max_words"
            )

        if not version.strip():
            raise ValueError("version cannot be empty")

        self.max_words = max_words
        self.overlap_words = overlap_words
        self.version = version

    def chunk(
        self,
        snapshot_id: str,
        clean_text: str,
    ) -> list[Passage]:
        words = clean_text.split()

        if not words:
            raise ValueError("clean_text cannot be empty")

        passages: list[Passage] = []
        step = self.max_words - self.overlap_words
        start = 0
        chunk_index = 0

        while start < len(words):
            chunk_words = words[start: start + self.max_words]
            text = " ".join(chunk_words)

            content_sha256 = hashlib.sha256(
                text.encode("utf-8")
            ).hexdigest()

            identity = (
                f"{snapshot_id}\0"
                f"{self.version}\0"
                f"{chunk_index}\0"
                f"{content_sha256}"
            )

            passage_hash = hashlib.sha256(
                identity.encode("utf-8")
            ).hexdigest()

            passages.append(
                Passage(
                    passage_id=f"P:{passage_hash}",
                    snapshot_id=snapshot_id,
                    chunk_index=chunk_index,
                    text=text,
                    content_sha256=content_sha256,
                    chunker_version=self.version,
                )
            )

            if start + self.max_words >= len(words):
                break

            start += step
            chunk_index += 1

        return passages
