"""Deterministic keyword baseline; scores are query coverage, not confidence."""
import re

from .repository import IndexSnapshot, Passage

STOP_WORDS = frozenset("a an the is are was were to from for of in on and or how what where do does i my".split())


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[^\W_]+", text.casefold())) - STOP_WORDS


def rank(snapshot: IndexSnapshot, question: str, top_k: int) -> list[tuple[Passage, float]]:
    query = tokens(question)
    if not query:
        return []
    matches = []
    for passage in snapshot.passages:
        overlap = len(query & tokens(passage.text))
        if overlap:
            matches.append((passage, overlap / len(query)))
    return sorted(matches, key=lambda item: (-item[1], item[0].passage_id))[:top_k]
