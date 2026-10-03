"""
Harma Runtime V3 — Experience Retriever (spec §8)

"Have I successfully performed this task, or a similar one, before?"

Retrieval is tiered so trivial commands stay cheap:
  * lightweight  — active corrections only (single indexed query)
  * full         — exact structural template matches (in-process cache), similar procedures
                   (token-structure similarity), relevant failures and semantic facts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from harma.core.v3.experience import templates as tpl
from harma.core.v3.experience.models import Correction, FailureExperience, Procedure
from harma.core.v3.experience.store import ExperienceStore


@dataclass
class RetrievedExperience:
    matches: list[tuple[Procedure, dict[str, str], str]] = field(default_factory=list)
    similar: list[tuple[Procedure, float, str]] = field(default_factory=list)
    failures: list[FailureExperience] = field(default_factory=list)
    corrections: list[Correction] = field(default_factory=list)
    facts: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: float = 0.0
    lightweight: bool = False
    store_ref: Any = None

    def summary(self) -> dict[str, Any]:
        return {
            "exact_matches": [(p.procedure_id, p.status.value, p.confidence) for p, _, _ in self.matches],
            "similar": [(p.procedure_id, s) for p, s, _ in self.similar],
            "failures": [f.failure_id for f in self.failures],
            "corrections": [c.correction_id for c in self.corrections],
            "lightweight": self.lightweight,
            "duration_ms": round(self.duration_ms, 2),
        }

    def to_untrusted_context(self, limit: int = 3) -> dict[str, Any]:
        """
        Structured, UNTRUSTED data for the LLM (spec §50). Never placed in system instructions;
        the runtime — not the model — decides whether any of it is usable.
        """
        procs = []
        seen = set()
        for p, _, template in self.matches:
            if p.procedure_id not in seen:
                seen.add(p.procedure_id)
                procs.append((p, template, 1.0))
        for p, sim, template in self.similar:
            if p.procedure_id not in seen:
                seen.add(p.procedure_id)
                procs.append((p, template, sim))
        data: dict[str, Any] = {}
        if procs:
            data["similar_procedures"] = [{
                "template": template,
                "steps": p.steps,
                "status": p.status.value,
                "confidence": p.confidence,
                "similarity": round(sim, 2),
                "known_failure_modes": p.known_failure_modes[-3:],
                "source": p.source,
            } for p, template, sim in procs[:limit]]
        if self.failures:
            data["failure_lessons"] = [{
                "task_pattern": f.task_pattern, "failure_type": f.failure_type,
                "reason": f.reason[:200], "better_strategy": f.better_strategy,
                "occurrences": f.occurrences,
            } for f in self.failures[:limit]]
        if self.corrections:
            data["user_preferences"] = [{
                "kind": c.kind, "subject": c.subject, "replaces": c.replaces,
                "source": c.source,
            } for c in self.corrections[:5] if c.kind in ("prefer", "avoid", "require_confirmation")]
        return data


class ExperienceRetriever:
    def __init__(self, store: ExperienceStore) -> None:
        self.store = store

    def retrieve(self, request: str, lightweight: bool = False) -> RetrievedExperience:
        t0 = time.perf_counter()
        out = RetrievedExperience(lightweight=lightweight, store_ref=self.store)
        try:
            out.corrections = self.store.active_corrections()
            out.matches = self.store.find_template_matches(request)   # in-process cache: cheap
            if not lightweight:
                out.similar = [s for s in self.store.find_similar(request, limit=3)
                               if s[0].procedure_id not in {m[0].procedure_id for m in out.matches}]
                patterns = {p.task_pattern for p, _, _ in out.matches} | {p.task_pattern for p, _, _ in out.similar}
                proc_ids = {p.procedure_id for p, _, _ in out.matches}
                fails: dict[str, FailureExperience] = {}
                for pid in proc_ids:
                    for f in self.store.failures_for(procedure_id=pid, limit=3):
                        fails[f.failure_id] = f
                for pat in patterns:
                    for f in self.store.failures_for(task_pattern=pat, limit=2):
                        fails[f.failure_id] = f
                norm = tpl.normalize_request(request).lower()
                for f in self.store.failures_for(template=norm, limit=2):
                    fails[f.failure_id] = f
                out.failures = sorted(fails.values(), key=lambda f: -f.updated_at)[:5]
        except Exception:
            pass
        out.duration_ms = (time.perf_counter() - t0) * 1000
        return out
