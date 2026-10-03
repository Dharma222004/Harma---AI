"""
Harma Performance Instrumentation — Phase 10.5

Provides high-resolution per-stage latency tracking for every agent request.

Usage:
    from harma.core.perf import RequestTrace, Stage

    trace = RequestTrace(request_id="harma-abc123", user_input="open chrome")
    trace.mark(Stage.LLM_REQUEST_START)
    ...
    trace.mark(Stage.LLM_REQUEST_END)
    summary = trace.summary()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from harma.config.logging_config import get_logger

log = get_logger(__name__)


class Stage(str, Enum):
    REQUEST_RECEIVED       = "request_received"
    MEMORY_RETRIEVAL_START = "memory_retrieval_start"
    MEMORY_RETRIEVAL_END   = "memory_retrieval_end"
    TOOL_DISCOVERY_START   = "tool_discovery_start"
    TOOL_DISCOVERY_END     = "tool_discovery_end"
    LLM_REQUEST_START      = "llm_request_start"
    LLM_REQUEST_END        = "llm_request_end"
    TOOL_EXECUTION_START   = "tool_execution_start"
    TOOL_EXECUTION_END     = "tool_execution_end"
    VERIFICATION_START     = "verification_start"
    VERIFICATION_END       = "verification_end"
    LLM_CONTINUATION_START = "llm_continuation_start"
    LLM_CONTINUATION_END   = "llm_continuation_end"
    API_RESPONSE           = "api_response"


@dataclass
class RequestTrace:
    """Per-request high-resolution latency trace."""

    request_id: str
    user_input: str
    start_time: float = field(default_factory=time.perf_counter)

    _marks: dict[str, float] = field(default_factory=dict)
    _llm_calls: int = 0
    _tool_calls: int = 0
    _screenshots: int = 0
    _retries: int = 0
    _tokens_in: int = 0
    _tokens_out: int = 0
    _selected_tools: int = 0
    _total_tools: int = 0

    def mark(self, stage: Stage) -> None:
        """Record a timestamp for a pipeline stage."""
        self._marks[stage.value] = time.perf_counter()

    def record_llm_call(self, tokens_in: int = 0, tokens_out: int = 0) -> None:
        self._llm_calls += 1
        self._tokens_in += tokens_in
        self._tokens_out += tokens_out

    def record_tool_call(self) -> None:
        self._tool_calls += 1

    def record_screenshot(self) -> None:
        self._screenshots += 1

    def record_retry(self) -> None:
        self._retries += 1

    def set_tool_counts(self, selected: int, total: int) -> None:
        self._selected_tools = selected
        self._total_tools = total

    # ── Duration helpers ──────────────────────────────────────────────────────

    def _dur_ms(self, start_stage: Stage, end_stage: Stage) -> Optional[float]:
        s = self._marks.get(start_stage.value)
        e = self._marks.get(end_stage.value)
        if s is not None and e is not None:
            return round((e - s) * 1000, 1)
        return None

    def total_ms(self) -> float:
        end = self._marks.get(Stage.API_RESPONSE.value, time.perf_counter())
        return round((end - self.start_time) * 1000, 1)

    # ── Reporting ─────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        """Return a structured performance summary dict."""
        dur = {
            "memory_retrieval_ms": self._dur_ms(Stage.MEMORY_RETRIEVAL_START, Stage.MEMORY_RETRIEVAL_END),
            "tool_discovery_ms":   self._dur_ms(Stage.TOOL_DISCOVERY_START, Stage.TOOL_DISCOVERY_END),
            "llm_ms":              self._dur_ms(Stage.LLM_REQUEST_START, Stage.LLM_REQUEST_END),
            "tool_execution_ms":   self._dur_ms(Stage.TOOL_EXECUTION_START, Stage.TOOL_EXECUTION_END),
            "verification_ms":     self._dur_ms(Stage.VERIFICATION_START, Stage.VERIFICATION_END),
            "continuation_ms":     self._dur_ms(Stage.LLM_CONTINUATION_START, Stage.LLM_CONTINUATION_END),
            "total_ms":            self.total_ms(),
        }
        counts = {
            "llm_calls":       self._llm_calls,
            "tool_calls":      self._tool_calls,
            "screenshots":     self._screenshots,
            "retries":         self._retries,
            "tokens_in":       self._tokens_in,
            "tokens_out":      self._tokens_out,
            "selected_tools":  self._selected_tools,
            "total_tools":     self._total_tools,
        }
        return {"request_id": self.request_id, "durations_ms": dur, "counts": counts}

    def log_trace(self) -> None:
        """Emit a human-readable performance trace to the log."""
        s = self.summary()
        d = s["durations_ms"]
        c = s["counts"]
        lines = [
            f"\n{'─'*60}",
            f"HARMA REQUEST TRACE  [{self.request_id}]",
            f"Request: {self.user_input[:80]}",
            f"{'─'*60}",
        ]
        for k, v in d.items():
            if v is not None:
                lines.append(f"  {k:<28} {v:>8.1f} ms")
        lines.append(f"{'─'*60}")
        lines.append(f"  LLM calls:         {c['llm_calls']}")
        lines.append(f"  Tool calls:        {c['tool_calls']}")
        lines.append(f"  Screenshots:       {c['screenshots']}")
        lines.append(f"  Retries:           {c['retries']}")
        lines.append(f"  Tokens in/out:     {c['tokens_in']}/{c['tokens_out']}")
        lines.append(f"  Selected tools:    {c['selected_tools']}/{c['total_tools']}")
        lines.append(f"{'─'*60}\n")
        log.info("\n".join(lines))


# ── Rolling metrics registry ───────────────────────────────────────────────────

_all_traces: list[dict] = []
_MAX_TRACES = 200


def record_trace(trace: RequestTrace) -> None:
    """Persist a completed trace for dashboard display."""
    global _all_traces
    _all_traces.append(trace.summary())
    if len(_all_traces) > _MAX_TRACES:
        _all_traces = _all_traces[-_MAX_TRACES:]


def get_performance_stats() -> dict:
    """Return aggregated performance statistics over recorded traces."""
    if not _all_traces:
        return {"total_requests": 0}

    totals = [t["durations_ms"]["total_ms"] for t in _all_traces if t["durations_ms"]["total_ms"]]
    llm_ms = [t["durations_ms"]["llm_ms"] for t in _all_traces if t["durations_ms"].get("llm_ms")]
    tool_ms = [t["durations_ms"]["tool_execution_ms"] for t in _all_traces if t["durations_ms"].get("tool_execution_ms")]
    llm_calls = [t["counts"]["llm_calls"] for t in _all_traces]
    tool_calls = [t["counts"]["tool_calls"] for t in _all_traces]
    screenshots = [t["counts"]["screenshots"] for t in _all_traces]
    tokens_in = [t["counts"]["tokens_in"] for t in _all_traces]

    def _pct(data: list[float], p: float) -> Optional[float]:
        if not data:
            return None
        s = sorted(data)
        idx = int(len(s) * p / 100)
        return round(s[min(idx, len(s) - 1)], 1)

    def _avg(data: list) -> Optional[float]:
        return round(sum(data) / len(data), 1) if data else None

    return {
        "total_requests": len(_all_traces),
        "total_latency": {
            "p50_ms": _pct(totals, 50),
            "p95_ms": _pct(totals, 95),
            "p99_ms": _pct(totals, 99),
            "avg_ms": _avg(totals),
        },
        "llm_latency": {
            "p50_ms": _pct(llm_ms, 50),
            "p95_ms": _pct(llm_ms, 95),
            "avg_ms": _avg(llm_ms),
        },
        "tool_latency": {
            "p50_ms": _pct(tool_ms, 50),
            "p95_ms": _pct(tool_ms, 95),
            "avg_ms": _avg(tool_ms),
        },
        "per_request_avg": {
            "llm_calls":    _avg(llm_calls),
            "tool_calls":   _avg(tool_calls),
            "screenshots":  _avg(screenshots),
            "tokens_in":    _avg(tokens_in),
        },
        "recent_traces": _all_traces[-20:][::-1],
    }
