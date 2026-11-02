from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator


@dataclass(frozen=True)
class AgentEvent:
    """A serializable event emitted by the shared Agent runtime."""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }


class EventSubscription(Iterator[AgentEvent]):
    """A cancellable blocking subscription to an :class:`EventHub`."""

    _CLOSED = object()

    def __init__(self, hub: EventHub, max_events: int) -> None:
        self._hub = hub
        self._events: queue.Queue[AgentEvent | object] = queue.Queue(maxsize=max_events)
        self._closed = threading.Event()

    def __iter__(self) -> EventSubscription:
        return self

    def __next__(self) -> AgentEvent:
        item = self._events.get()
        if item is self._CLOSED:
            raise StopIteration
        return item  # type: ignore[return-value]

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        self._hub.unsubscribe(self)
        self._wake()

    def _wake(self) -> None:
        try:
            self._events.put_nowait(self._CLOSED)
        except queue.Full:
            try:
                self._events.get_nowait()
            except queue.Empty:
                pass
            try:
                self._events.put_nowait(self._CLOSED)
            except queue.Full:
                pass

    def _push(self, event: AgentEvent) -> None:
        if self._closed.is_set():
            return
        try:
            self._events.put_nowait(event)
        except queue.Full:
            # A disconnected or slow UI must not block the Agent runtime.
            try:
                self._events.get_nowait()
            except queue.Empty:
                return
            try:
                self._events.put_nowait(event)
            except queue.Full:
                pass


class EventHub:
    """Thread-safe fan-out hub for local Agent runtime events."""

    def __init__(self, *, subscription_queue_size: int = 128) -> None:
        if subscription_queue_size < 1:
            raise ValueError("subscription_queue_size must be positive")
        self._subscription_queue_size = subscription_queue_size
        self._subscriptions: set[EventSubscription] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> EventSubscription:
        subscription = EventSubscription(self, self._subscription_queue_size)
        with self._lock:
            self._subscriptions.add(subscription)
        return subscription

    def unsubscribe(self, subscription: EventSubscription) -> None:
        with self._lock:
            self._subscriptions.discard(subscription)

    def publish(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> AgentEvent:
        event_type = event_type.strip()
        if not event_type:
            raise ValueError("event_type cannot be empty")
        event = AgentEvent(event_type, dict(payload or {}))
        with self._lock:
            subscriptions = tuple(self._subscriptions)
        for subscription in subscriptions:
            subscription._push(event)
        return event

