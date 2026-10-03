"""
Harma Runtime V3 — Experience Analyzer (spec §37, §43, §44)

Offline / background analysis of past executions. Never runs synchronously on the
task path — the runner schedules it in a worker thread every N runs.

Discovers:
  * repeated successful patterns         * repeated failure patterns
  * common recovery lessons              * slow steps
  * unnecessary LLM calls (procedures that are trusted but still used LLM reasoning)
And applies experience decay (recency) to procedure confidence/status.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from typing import Any

from harma.config.logging_config import get_logger
from harma.core.v3.experience import templates as tpl
from harma.core.v3.experience.models import ProcedureStatus, refresh
from harma.core.v3.experience.store import ExperienceStore

log = get_logger(__name__)


class ExperienceAnalyzer:
    def __init__(self, store: ExperienceStore, slow_step_ms: float = 4000.0) -> None:
        self.store = store
        self.slow_step_ms = slow_step_ms
        self.last_report: dict[str, Any] = {}

    def analyze(self, window_days: float = 30.0, now: float | None = None) -> dict[str, Any]:
        now = now or time.time()
        since = now - window_days * 86400
        episodes = self.store.recent_episodes(limit=500, since=since)

        by_template: dict[str, Counter] = defaultdict(Counter)
        tool_durations: dict[str, list[float]] = defaultdict(list)
        llm_by_proc: dict[str, list[int]] = defaultdict(list)
        for ep in episodes:
            if ep.get("template"):
                by_template[ep["template"]][ep.get("outcome", "")] += 1
            for st in ep.get("steps", []):
                if st.get("duration_ms"):
                    tool_durations[st["tool"]].append(float(st["duration_ms"]))
            if ep.get("procedure_id") and ep.get("strategy") == "known_procedure":
                llm_by_proc[ep["procedure_id"]].append(int(ep.get("llm_calls", 0)))

        successful_patterns = sorted(
            [{"template": t, "verified": c["verified"], "failed": c["failed"]}
             for t, c in by_template.items() if c["verified"] >= 2],
            key=lambda d: -d["verified"])[:10]

        failure_patterns = [
            {"task_pattern": f.task_pattern, "failure_type": f.failure_type,
             "occurrences": f.occurrences, "better_strategy": f.better_strategy}
            for f in self.store.failures_for(limit=50) if f.occurrences >= 2
        ][:10]
        recovery_lessons = [
            {"task_pattern": f.task_pattern, "lesson": f.better_strategy}
            for f in self.store.failures_for(limit=50) if f.better_strategy.startswith("recovered by:")
        ][:10]

        slow_steps = sorted(
            [{"tool": t, "avg_ms": round(sum(v) / len(v), 1), "samples": len(v)}
             for t, v in tool_durations.items() if v and sum(v) / len(v) >= self.slow_step_ms],
            key=lambda d: -d["avg_ms"])[:10]

        unnecessary_llm = []
        for pid, calls in llm_by_proc.items():
            if calls and sum(calls) > 0:
                proc = self.store.get_procedure(pid)
                if proc and proc.status == ProcedureStatus.TRUSTED:
                    unnecessary_llm.append({"procedure_id": pid, "llm_calls": sum(calls), "runs": len(calls)})

        decayed = self.apply_decay(now)
        report = {
            "analyzed_at": now, "episodes": len(episodes),
            "successful_patterns": successful_patterns, "failure_patterns": failure_patterns,
            "recovery_lessons": recovery_lessons, "slow_steps": slow_steps,
            "unnecessary_llm_calls": unnecessary_llm[:10], "decayed_procedures": decayed,
            "store": self.store.stats(),
        }
        self.last_report = report
        log.info("[V3][ANALYZER] %d episodes, %d patterns, %d failure patterns, %d decayed",
                 len(episodes), len(successful_patterns), len(failure_patterns), len(decayed))
        return report

    def apply_decay(self, now: float | None = None) -> list[dict[str, Any]]:
        """Recompute confidence with recency so stale experience gradually loses priority."""
        changed = []
        for proc in self.store.list_procedures(limit=1000):
            before = (proc.status, proc.confidence)
            refresh(proc, now)
            if (proc.status, proc.confidence) != before:
                self.store.upsert_procedure(proc, tpl.procedure_key(proc.steps))
                changed.append({"procedure_id": proc.procedure_id, "from": [before[0].value, before[1]],
                                "to": [proc.status.value, proc.confidence]})
        return changed
