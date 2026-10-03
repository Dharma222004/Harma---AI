"""
Harma Structured Telemetry

Records structured spans for planning, execution, and verification latency,
with strict redaction of credentials, tokens, and sensitive data.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from harma.config.logging_config import get_logger

log = get_logger(__name__)

# Patterns to scrub from telemetry
_SECRET_PATTERNS = [
    r"ghp_[a-zA-Z0-9]{36,}",
    r"xox[baprs]-[0-9a-zA-Z-]+",
    r"AIza[0-9A-Za-z-_]{35}",
    r"gsk_[a-zA-Z0-9]{40,}",
    r"Bearer\s+[a-zA-Z0-9_\-\.]+",
    r"password[\"']?\s*[:=]\s*[\"']?[^\"'\s]+",
]


@dataclass
class TelemetrySpan:
    """A single trace span in Harma's execution pipeline."""
    span_id: str
    name: str
    request_id: str = ""
    plan_id: str = ""
    step_id: Optional[int] = None
    tool_name: str = ""
    model: str = ""
    provider: str = ""
    duration_ms: float = 0.0
    tokens_used: int = 0
    retry_count: int = 0
    success: bool = True
    verification_status: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    start_time: float = field(default_factory=time.time)

    def finish(self, success: bool = True, verification_status: str = "") -> None:
        self.duration_ms = (time.time() - self.start_time) * 1000.0
        self.success = success
        self.verification_status = verification_status


class StructuredTelemetry:
    """
    Collector and logger for execution traces and observability.
    """

    def __init__(self) -> None:
        self.spans: list[TelemetrySpan] = []

    def start_span(self, name: str, **kwargs: Any) -> TelemetrySpan:
        """Start a new telemetry span."""
        span_id = f"span_{len(self.spans) + 1}"
        span = TelemetrySpan(span_id=span_id, name=name, **kwargs)
        self.spans.append(span)
        return span

    def scrub(self, text: str) -> str:
        """Redact sensitive credentials from telemetry logs."""
        scrubbed = text
        for pat in _SECRET_PATTERNS:
            scrubbed = re.sub(pat, "[REDACTED_SECRET]", scrubbed)
        return scrubbed

    def log_span(self, span: TelemetrySpan) -> None:
        """Log finished span details."""
        safe_tool = self.scrub(span.tool_name)
        log.info(
            "[TELEMETRY] Span=%s tool=%s duration=%.2fms success=%s verif=%s",
            span.name,
            safe_tool,
            span.duration_ms,
            span.success,
            span.verification_status,
        )

    def summary(self) -> dict[str, Any]:
        """Aggregate performance summary."""
        total = len(self.spans)
        successes = sum(1 for s in self.spans if s.success)
        total_time = sum(s.duration_ms for s in self.spans)
        avg_time = (total_time / total) if total > 0 else 0.0
        return {
            "total_spans": total,
            "success_rate": (successes / total) if total > 0 else 1.0,
            "avg_latency_ms": round(avg_time, 2),
            "total_duration_ms": round(total_time, 2),
        }
