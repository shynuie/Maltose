"""Typed execution lifecycle events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable


class ExecutionEventType(StrEnum):
    QUEUED = "execution.queued"
    APPROVAL_REQUIRED = "execution.approval_required"
    RUNNING = "execution.running"
    COMPLETED = "execution.completed"
    FAILED = "execution.failed"
    TIMED_OUT = "execution.timed_out"
    OUTPUT_LIMIT_EXCEEDED = "execution.output_limit_exceeded"


@dataclass(frozen=True)
class ExecutionEvent:
    type: ExecutionEventType
    execution_id: str
    payload: dict[str, Any]


ExecutionEventPublisher = Callable[[ExecutionEvent], None]


def publish_to_event_hub(hub: Any) -> ExecutionEventPublisher:
    """Adapt typed execution events to the shared Web UI EventHub."""
    def publish(event: ExecutionEvent) -> None:
        hub.publish(event.type.value, {
            "execution_id": event.execution_id,
            **event.payload,
        })
    return publish
