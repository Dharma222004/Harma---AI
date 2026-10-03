"""
Harma Runtime V3 — Strategy Selector & Reasoning Gate (spec §14–16, §19, §45)

Priority:  verified known strategy → deterministic workflow → new plan → deep reasoning,
with risk and environment compatibility overriding blind reuse.

    StrategyScore = reliability × environment_match × confidence × safety ÷ expected_cost

Learned procedures are DATA, not authority: selecting one only proposes steps. Every
step still goes through ToolRuntime (permission, risk, confirmation, verification).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from harma.core.v3 import toolmeta
from harma.core.v3.experience import templates as tpl
from harma.core.v3.experience.feedback import apply_corrections
from harma.core.v3.experience.models import (
    CANDIDATE_REUSE_MIN_CONFIDENCE, Procedure, ProcedureStatus,
)
from harma.core.v3.experience.retriever import RetrievedExperience
from harma.core.v3.intent import Intent
from harma.core.v3.state import ReasoningDecision, StrategyType, TaskType

_SAFETY = {"low": 1.0, "medium": 0.85, "high": 0.6}


@dataclass
class StrategyDecision:
    strategy: StrategyType
    reasoning: ReasoningDecision
    steps: list[dict[str, Any]] = field(default_factory=list)
    procedure: Optional[Procedure] = None
    bindings: dict[str, str] = field(default_factory=dict)
    template: str = ""
    score: float = 0.0
    reason: str = ""
    rejected: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: float = 0.0


class ReasoningGate:
    """Decides whether LLM reasoning is genuinely necessary (spec §19)."""

    @staticmethod
    def for_strategy(strategy: StrategyType) -> ReasoningDecision:
        if strategy in (StrategyType.FAST_DETERMINISTIC, StrategyType.KNOWN_PROCEDURE,
                        StrategyType.KNOWN_WORKFLOW, StrategyType.APPLY_FEEDBACK):
            return ReasoningDecision.NO_LLM
        if strategy == StrategyType.ASK_USER:
            return ReasoningDecision.DISAMBIGUATE
        if strategy == StrategyType.LLM_RECOVERY:
            return ReasoningDecision.RECOVER
        return ReasoningDecision.PLAN

    @staticmethod
    def for_failure(strategy: Optional[StrategyType], recovery_action: str) -> ReasoningDecision:
        """After a failure: deterministic retry needs no LLM; a reused procedure is adapted (REPLAN);
        an LLM-generated plan is repaired (RECOVER)."""
        if recovery_action == "retry":
            return ReasoningDecision.NO_LLM
        if strategy in (StrategyType.KNOWN_PROCEDURE, StrategyType.KNOWN_WORKFLOW, StrategyType.FAST_DETERMINISTIC):
            return ReasoningDecision.REPLAN
        return ReasoningDecision.RECOVER


def strategy_score(proc: Procedure, env_match: float) -> float:
    attempts = proc.success_count + proc.failure_count
    reliability = (proc.success_count + 1.0) / (attempts + 2.0)
    safety = _SAFETY.get(proc.risk_level, 0.85)
    expected_cost = 1.0 + (proc.avg_latency_ms / 1000.0) * 0.1 + proc.avg_llm_calls * 0.5
    return round(reliability * env_match * max(proc.confidence, 0.01) * safety / expected_cost, 4)


class StrategySelector:
    def __init__(self, registry: Any, platform: str = "") -> None:
        self.registry = registry
        self.platform = platform

    # ── Validation of a learned procedure (spec §15) ─────────────────────────

    def validate_procedure(self, proc: Procedure, bindings: dict[str, str], corrections: list) -> tuple[bool, str, list[dict[str, Any]], float]:
        if proc.status in (ProcedureStatus.DISABLED, ProcedureStatus.UNVERIFIED):
            return False, f"procedure is {proc.status.value}", [], 0.0
        if proc.status == ProcedureStatus.CANDIDATE:
            if proc.confidence < CANDIDATE_REUSE_MIN_CONFIDENCE:
                return False, "candidate confidence too low", [], 0.0
            if proc.risk_level == "high":
                return False, "high-risk candidate needs fresh planning", [], 0.0
            if proc.consecutive_failures > 1:
                return False, "recent repeated failures", [], 0.0
        missing_slots = [s for s in proc.slots if s not in bindings]
        if missing_slots:
            return False, f"unbound slots {missing_slots}", [], 0.0
        env_match = 1.0
        if proc.environment.get("platform") and self.platform and proc.environment["platform"] != self.platform:
            env_match = 0.5
        steps = tpl.instantiate_steps(proc.steps, bindings)
        for st in steps:
            tool = self.registry.get(st["tool"])
            if tool is None:
                return False, f"tool '{st['tool']}' no longer available", [], 0.0
            for req in toolmeta.required_params(tool):
                val = st["arguments"].get(req)
                if val is None or (isinstance(val, str) and not val.strip()):
                    return False, f"required argument '{req}' missing for {st['tool']}", [], 0.0
        steps, blocked = apply_corrections(steps, corrections)
        if blocked:
            return False, blocked, [], 0.0
        return True, "ok", steps, env_match

    # ── Selection ─────────────────────────────────────────────────────────────

    def select(self, intent: Intent, exp: RetrievedExperience) -> StrategyDecision:
        t0 = time.perf_counter()
        d = self._select(intent, exp)
        d.reasoning = ReasoningGate.for_strategy(d.strategy)
        d.duration_ms = (time.perf_counter() - t0) * 1000
        return d

    def _select(self, intent: Intent, exp: RetrievedExperience) -> StrategyDecision:
        if intent.task_type == TaskType.FEEDBACK:
            return StrategyDecision(StrategyType.APPLY_FEEDBACK, ReasoningDecision.NO_LLM, reason="explicit user feedback")
        if intent.task_type == TaskType.AMBIGUOUS:
            return StrategyDecision(StrategyType.ASK_USER, ReasoningDecision.DISAMBIGUATE, reason="request lacks a referent")

        if intent.task_type in (TaskType.CONVERSATIONAL, TaskType.RECOVERY):
            return StrategyDecision(StrategyType.LLM_PLAN, ReasoningDecision.PLAN, reason=intent.task_type.value)

        # 1. Verified known procedure (exact structural match) — experience outranks grammar
        rejected: list[dict[str, Any]] = []
        best: Optional[StrategyDecision] = None
        for proc, bindings, template in exp.matches:
            ok, why, steps, env_match = self.validate_procedure(proc, bindings, exp.corrections)
            if not ok:
                rejected.append({"procedure_id": proc.procedure_id, "reason": why})
                continue
            score = strategy_score(proc, env_match)
            if best is None or score > best.score:
                best = StrategyDecision(StrategyType.KNOWN_PROCEDURE, ReasoningDecision.NO_LLM, steps=steps,
                                        procedure=proc, bindings=bindings, template=template, score=score,
                                        reason=f"{proc.status.value} procedure (confidence {proc.confidence})")
        if best is not None:
            best.rejected = rejected
            return best

        # 2. Deterministic single action
        if intent.task_type == TaskType.SIMPLE_DETERMINISTIC and intent.fast_tool:
            steps, blocked = apply_corrections([{"tool": intent.fast_tool, "arguments": dict(intent.fast_args)}],
                                               exp.corrections)
            if not blocked:
                return StrategyDecision(StrategyType.FAST_DETERMINISTIC, ReasoningDecision.NO_LLM, steps=steps,
                                        score=1.0, reason="deterministic single action", rejected=rejected)
            return StrategyDecision(StrategyType.LLM_PLAN, ReasoningDecision.PLAN,
                                    reason=f"deterministic action {blocked}", rejected=rejected)

        # 2. Deterministic workflow composed of known procedures / deterministic actions
        wf = self._compose_workflow(intent, exp)
        if wf is not None:
            wf.rejected = rejected
            return wf

        # 3. New plan (similar experience passed as untrusted hints)
        reason = "no reusable verified procedure"
        if rejected:
            reason += f" ({rejected[0]['reason']})"
        return StrategyDecision(StrategyType.LLM_PLAN, ReasoningDecision.PLAN, reason=reason, rejected=rejected)

    # ── Workflow composition (spec §14 KNOWN_WORKFLOW) ───────────────────────

    _SPLIT = re.compile(r"\s*(?:,\s*)?\b(?:and then|then|and)\b\s*", re.I)

    def _split_clauses(self, text: str) -> list[str]:
        # Split on connectives outside quotes only.
        parts, buf = [], ""
        tokens = re.split(r"(\"[^\"]*\"|'[^']*')", text)
        for tok in tokens:
            if tok.startswith(("\"", "'")) and len(tok) >= 2:
                buf += tok
                continue
            pieces = self._SPLIT.split(tok)
            buf += pieces[0]
            for p in pieces[1:]:
                parts.append(buf)
                buf = p
        parts.append(buf)
        return [p.strip(" ,") for p in parts if p.strip(" ,")]

    def _compose_workflow(self, intent: Intent, exp: RetrievedExperience) -> Optional[StrategyDecision]:
        if not intent.compound or exp.store_ref is None:
            return None
        clauses = self._split_clauses(intent.goal)
        if len(clauses) < 2 or len(clauses) > 5:
            return None
        from harma.core.v3.intent import IntentGateway
        gateway = IntentGateway(self.registry)
        all_steps: list[dict[str, Any]] = []
        used: list[str] = []
        min_conf = 1.0
        for clause in clauses:
            ci = gateway.classify(clause, has_history=True)
            if ci.task_type == TaskType.SIMPLE_DETERMINISTIC and ci.fast_tool:
                all_steps.append({"tool": ci.fast_tool, "arguments": dict(ci.fast_args)})
                continue
            matched = False
            for proc, bindings, _template in exp.store_ref.find_template_matches(clause):
                if proc.status != ProcedureStatus.TRUSTED:
                    continue
                ok, _why, steps, _env = self.validate_procedure(proc, bindings, exp.corrections)
                if ok:
                    all_steps.extend(steps)
                    used.append(proc.procedure_id)
                    min_conf = min(min_conf, proc.confidence)
                    matched = True
                    break
            if not matched:
                return None
        if not used:
            return None   # purely deterministic compound requests still go through planning
        all_steps, blocked = apply_corrections(all_steps, exp.corrections)
        if blocked:
            return None
        return StrategyDecision(StrategyType.KNOWN_WORKFLOW, ReasoningDecision.NO_LLM, steps=all_steps,
                                score=round(min_conf, 3),
                                reason=f"workflow composed from trusted procedures {used}")
