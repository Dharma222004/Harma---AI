"""
Harma Runtime V3 — Structured Run Events (spec §53)

Events are published to the existing global EventBus (Control Center subscribes to it)
under the `v3.` prefix. The UI observes; it never controls the runtime directly.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from harma.config.logging_config import get_logger

log = get_logger(__name__)

EVENT_TYPES = frozenset({
    "RunCreated", "IntentNormalized", "TaskClassified", "ExperienceRetrieved",
    "StrategySelected", "PlanCreated", "ToolStarted", "ToolCompleted",
    "ObservationCreated", "VerificationCompleted", "RecoveryStarted", "ReplanCreated",
    "ExperienceCreated", "ExperienceUpdated", "RunCompleted", "RunFailed",
    "RunPaused", "RunCancelled", "StateTransition",
})


def emit(state: Any, event_type: str, payload: Optional[dict[str, Any]] = None, severity: str = "info") -> None:
    """Record an event on the run state and fan it out to the global event bus."""
    if event_type not in EVENT_TYPES:
        log.debug("[V3][EVENTS] Unknown event type %s", event_type)
    data = {"run_id": getattr(state, "run_id", ""), **(payload or {})}
    record = {"type": event_type, "t": time.time(), "payload": data}
    try:
        state.events.append(record)
    except Exception:
        pass

    try:
        from harma.api.events import get_event_bus
        from harma.api.models import EventSeverity
        sev = {
            "info": EventSeverity.INFO,
            "warning": EventSeverity.WARNING,
            "error": EventSeverity.ERROR,
        }.get(severity, EventSeverity.INFO)
        get_event_bus().publish(event_type=f"v3.{event_type}", source="harma_runner", severity=sev, payload=data)
    except Exception as exc:  # Event delivery must never break execution
        log.debug("[V3][EVENTS] publish failed for %s: %s", event_type, exc)
