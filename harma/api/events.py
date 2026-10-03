"""
Harma Real-Time Event Bus

Provides an asynchronous pub/sub event bus for broadcasting normalized HarmaEvent
objects across WebSocket connections and internal listeners.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from harma.api.models import EventSeverity, HarmaEvent
from harma.config.logging_config import get_logger

log = get_logger(__name__)


class EventBus:
    """
    Central event distributor with history buffer and subscriber queues.
    """

    def __init__(self, max_history: int = 200) -> None:
        self._subscribers: set[asyncio.Queue[HarmaEvent]] = set()
        self._history: list[HarmaEvent] = []
        self._max_history = max_history

    def publish(
        self,
        event_type: str,
        source: str = "system",
        severity: EventSeverity = EventSeverity.INFO,
        payload: Optional[dict[str, Any]] = None,
    ) -> HarmaEvent:
        """
        Create, buffer, and fan-out a new HarmaEvent to all active subscribers.
        """
        event = HarmaEvent(
            event_type=event_type,
            source=source,
            severity=severity,
            payload=payload or {},
        )

        # Buffer history
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        # Fan-out to subscriber queues without blocking
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("[EVENT_BUS] Queue full for subscriber, dropping oldest event")
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    pass

        log.debug("[EVENT] %s [%s] from %s", event_type, severity.value, source)
        return event

    def subscribe(self, maxsize: int = 100) -> asyncio.Queue[HarmaEvent]:
        """Register a new consumer queue."""
        q: asyncio.Queue[HarmaEvent] = asyncio.Queue(maxsize=maxsize)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[HarmaEvent]) -> None:
        """Unregister a consumer queue."""
        self._subscribers.discard(q)

    def get_history(
        self,
        limit: int = 50,
        filter_type: Optional[str] = None,
    ) -> list[HarmaEvent]:
        """Retrieve recent events, optionally filtered by event type prefix."""
        events = self._history
        if filter_type:
            events = [e for e in events if filter_type.lower() in e.event_type.lower()]
        return events[-limit:]

    def clear(self) -> None:
        """Clear event history."""
        self._history.clear()


_GLOBAL_EVENT_BUS: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Retrieve or initialize the global EventBus singleton."""
    global _GLOBAL_EVENT_BUS
    if _GLOBAL_EVENT_BUS is None:
        _GLOBAL_EVENT_BUS = EventBus()
    return _GLOBAL_EVENT_BUS
