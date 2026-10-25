from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json


from indexing_worker.models import (
    ContractError,
    DocumentUpdateEvent,
)
from indexing_worker.worker import (
    ProcessingAction,
    ProcessingResult,
)
from typing import Protocol


class MessageAction(str, Enum):
    ACK = "ack"
    REQUEUE = "requeue"
    DEAD_LETTER = "dead_letter"


@dataclass(frozen=True, slots=True)
class MessageDecision:
    action: MessageAction
    event_id: str | None = None
    error: str | None = None


class ProcessingWorker(Protocol):
    def process(
        self,
        event: DocumentUpdateEvent,
    ) -> ProcessingResult:
        ...


class RabbitMessageHandler:
    """
    Convert a RabbitMQ message into an acknowledgement decision.

    Actual ACK/NACK/publishing is left to the future Pika adapter.
    """

    def __init__(
        self,
        worker: ProcessingWorker,
    ) -> None:
        self.worker = worker

    def handle(
        self,
        body: bytes,
    ) -> MessageDecision:
        try:
            decoded = body.decode("utf-8")
            payload = json.loads(decoded)

            if not isinstance(payload, dict):
                raise ContractError(
                    "event payload must be a JSON object"
                )

            event = DocumentUpdateEvent.from_dict(payload)

        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            ContractError,
        ) as error:
            return MessageDecision(
                action=MessageAction.DEAD_LETTER,
                error=str(error) or error.__class__.__name__,
            )

        result = self.worker.process(event)

        if result.action in {
            ProcessingAction.ACK_COMPLETED,
            ProcessingAction.ACK_DUPLICATE,
            ProcessingAction.ACK_OBSOLETE,
        }:
            return MessageDecision(
                action=MessageAction.ACK,
                event_id=event.event_id,
            )

        if result.action == ProcessingAction.RETRY:
            return MessageDecision(
                action=MessageAction.REQUEUE,
                event_id=event.event_id,
                error=result.error,
            )

        return MessageDecision(
            action=MessageAction.DEAD_LETTER,
            event_id=event.event_id,
            error=result.error,
        )
