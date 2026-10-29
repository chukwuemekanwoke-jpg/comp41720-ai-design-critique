"""Synthetic fixtures only: these passages are not official guidance."""
from datetime import datetime, timezone
from hashlib import sha256

from .repository import IndexSnapshot, InMemoryPassageRepository, Passage


def demo_repository() -> InMemoryPassageRepository:
    texts = (
        ("S001", "Synthetic demo only: Stamp 1G graduate requirements checklist."),
        ("S002", "Synthetic demo only: Stamp 2 student registration renewal documents."),
        ("S003", "Synthetic demo only: appointment booking and registration information."),
    )
    passages = tuple(
        Passage(f"demo-p-{i}", source_id,
                f"{source_id}:{sha256(text.encode()).hexdigest()}", 1,
                "https://www.irishimmigration.ie/", text)
        for i, (source_id, text) in enumerate(texts, start=1)
    )
    repository = InMemoryPassageRepository()
    repository.publish(IndexSnapshot("demo-idx-001", datetime(2026, 10, 27, 12, tzinfo=timezone.utc), passages))
    return repository
