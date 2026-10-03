"""
Harma Runtime V3 — Authoritative Run State

`HarmaRunState` is the single source of truth for one agent run. Every node in the
execution graph reads and writes this object; no competing execution state exists.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


# ── Enumerations ──────────────────────────────────────────────────────────────

class RunStatus(str, Enum):
    """Explicit, observable execution states (spec §6)."""
    IDLE                      = "idle"
    RECEIVED                  = "received"
    UNDERSTANDING             = "understanding"
    ROUTING                   = "routing"
    RETRIEVING_EXPERIENCE     = "retrieving_experience"
    SELECTING_STRATEGY        = "selecting_strategy"
    PLANNING                  = "planning"
    WAITING_FOR_CONFIRMATION  = "waiting_for_confirmation"
    EXECUTING                 = "executing"
    OBSERVING                 = "observing"
    VERIFYING                 = "verifying"
    LEARNING                  = "learning"
    RECOVERING                = "recovering"
    REPLANNING                = "replanning"
    PAUSED                    = "paused"
    CANCELLING                = "cancelling"
    COMPLETED                 = "completed"
    FAILED                    = "failed"
    CANCELLED                 = "cancelled"


TERMINAL_STATUSES = frozenset({RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED})


class TaskType(str, Enum):
    """Cheap, pre-reasoning task classification (spec §7)."""
    SIMPLE_DETERMINISTIC = "simple_deterministic"
    KNOWN_PROCEDURE      = "known_procedure"
    KNOWN_WORKFLOW       = "known_workflow"
    MULTI_STEP           = "multi_step"
    COMPLEX_REASONING    = "complex_reasoning"
    AMBIGUOUS            = "ambiguous"
    RECOVERY             = "recovery"
    CONSEQUENTIAL_ACTION = "consequential_action"
    CONVERSATIONAL       = "conversational"
    FEEDBACK             = "feedback"


class StrategyType(str, Enum):
    """Execution strategies (spec §14)."""
    FAST_DETERMINISTIC = "fast_deterministic"
    KNOWN_PROCEDURE    = "known_procedure"
    KNOWN_WORKFLOW     = "known_workflow"
    LLM_PLAN           = "llm_plan"
    LLM_RECOVERY       = "llm_recovery"
    ASK_USER           = "ask_user"
    APPLY_FEEDBACK     = "apply_feedback"


class VerificationState(str, Enum):
    """Per-step verification states (spec §26)."""
    NOT_REQUIRED = "not_required"
    PENDING      = "pending"
    VERIFIED     = "verified"
    UNVERIFIED   = "unverified"
    FAILED       = "failed"


class StepStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    SUCCEEDED = "succeeded"
    FAILED    = "failed"
    SKIPPED   = "skipped"


class ReasoningDecision(str, Enum):
    """Output of the ReasoningGate (spec §19)."""
    NO_LLM       = "no_llm"
    PLAN         = "plan"
    REPLAN       = "replan"
    RECOVER      = "recover"
    DISAMBIGUATE = "disambiguate"


# ── Plan model ────────────────────────────────────────────────────────────────

@dataclass
class PlanStep:
    """One executable tool step in a plan."""
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    step_id: str = field(default_factory=lambda: f"s_{uuid.uuid4().hex[:6]}")
    description: str = ""
    source: str = "llm"                   # llm | procedure | deterministic | recovery
    llm_call_id: str = ""                 # provider tool-call id (for transcript continuity)
    depends_on: list[str] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    verification: VerificationState = VerificationState.PENDING
    attempts: int = 0
    result_summary: str = ""
    error: Optional[dict[str, Any]] = None
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["verification"] = self.verification.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PlanStep":
        d = dict(d)
        d["status"] = StepStatus(d.get("status", "pending"))
        d["verification"] = VerificationState(d.get("verification", "pending"))
        return cls(**d)


@dataclass
class Plan:
    steps: list[PlanStep] = field(default_factory=list)
    origin: str = "llm"                   # llm | procedure | deterministic

    def next_pending(self) -> Optional[PlanStep]:
        for s in self.steps:
            if s.status == StepStatus.PENDING:
                return s
        return None

    def pending_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status == StepStatus.PENDING]

    def completed_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status == StepStatus.SUCCEEDED]

    def is_complete(self) -> bool:
        return all(s.status in (StepStatus.SUCCEEDED, StepStatus.SKIPPED) for s in self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {"origin": self.origin, "steps": [s.to_dict() for s in self.steps]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Plan":
        return cls(steps=[PlanStep.from_dict(s) for s in d.get("steps", [])], origin=d.get("origin", "llm"))


# ── Run state ─────────────────────────────────────────────────────────────────

@dataclass
class HarmaRunState:
    """Authoritative state for a single run (spec §5)."""

    raw_request: str
    run_id: str = field(default_factory=lambda: f"run_{uuid.uuid4().hex[:10]}")
    normalized_goal: str = ""

    task_type: TaskType = TaskType.COMPLEX_REASONING
    risk_level: str = "low"
    domains: list[str] = field(default_factory=list)

    strategy_type: Optional[StrategyType] = None
    strategy_id: str = ""                  # procedure id when reusing experience
    strategy_score: float = 0.0
    strategy_reason: str = ""
    slot_bindings: dict[str, str] = field(default_factory=dict)

    status: RunStatus = RunStatus.IDLE
    status_history: list[dict[str, Any]] = field(default_factory=list)
    current_node: str = ""

    plan: Plan = field(default_factory=Plan)
    current_step: Optional[str] = None

    active_tool: str = ""
    active_tool_call_id: str = ""

    tool_results: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)

    verification_state: VerificationState = VerificationState.PENDING
    permission_state: dict[str, Any] = field(default_factory=dict)
    confirmation_state: dict[str, Any] = field(default_factory=dict)

    working_memory: dict[str, Any] = field(default_factory=dict)
    relevant_experiences: dict[str, Any] = field(default_factory=dict)
    environment_context: dict[str, Any] = field(default_factory=dict)

    retry_count: int = 0
    recovery_count: int = 0
    replan_count: int = 0
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0

    progress_score: float = 0.0
    loop_fingerprints: list[str] = field(default_factory=list)
    side_effect_fingerprints: dict[str, str] = field(default_factory=dict)   # fp -> step_id

    started_at: float = field(default_factory=time.time)
    deadline: Optional[float] = None
    first_action_at: Optional[float] = None

    pause_requested: bool = False
    cancel_requested: bool = False

    last_error: Optional[dict[str, Any]] = None
    failure_classification: str = ""
    final_outcome: str = ""                # verified | unverified | failed | cancelled | answered
    result: str = ""

    timings_ms: dict[str, float] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    # ── State transitions ─────────────────────────────────────────────────────

    def transition(self, new_status: RunStatus, node: str = "", reason: str = "") -> None:
        old = self.status
        self.status = new_status
        if node:
            self.current_node = node
        self.status_history.append({
            "from": old.value, "to": new_status.value,
            "node": node, "reason": reason, "t": time.time(),
        })

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    # ── Timing ────────────────────────────────────────────────────────────────

    def add_timing(self, key: str, ms: float) -> None:
        self.timings_ms[key] = round(self.timings_ms.get(key, 0.0) + ms, 2)

    def elapsed_ms(self) -> float:
        return (time.time() - self.started_at) * 1000.0

    # ── Progress / loops ──────────────────────────────────────────────────────

    def update_progress(self) -> None:
        total = len(self.plan.steps) or 1
        self.progress_score = round(len(self.plan.completed_steps()) / total, 3)

    def record_loop_fingerprint(self, fp: str) -> bool:
        """Record an action+state+result fingerprint. Returns True when a loop is detected."""
        self.loop_fingerprints.append(fp)
        return self.loop_fingerprints.count(fp) >= 3

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        for k, v in self.__dict__.items():
            if k == "working_memory":
                # Provider message objects are not JSON-serialisable; keep only plain data.
                d[k] = {wk: wv for wk, wv in v.items() if wk != "messages"}
            elif isinstance(v, Enum):
                d[k] = v.value
            elif isinstance(v, Plan):
                d[k] = v.to_dict()
            else:
                d[k] = v
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HarmaRunState":
        d = dict(d)
        d["status"] = RunStatus(d.get("status", "idle"))
        d["task_type"] = TaskType(d.get("task_type", TaskType.COMPLEX_REASONING.value))
        if d.get("strategy_type"):
            d["strategy_type"] = StrategyType(d["strategy_type"])
        d["verification_state"] = VerificationState(d.get("verification_state", "pending"))
        d["plan"] = Plan.from_dict(d.get("plan") or {})
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "task_type": self.task_type.value,
            "strategy": self.strategy_type.value if self.strategy_type else None,
            "strategy_id": self.strategy_id,
            "outcome": self.final_outcome,
            "steps": [s.to_dict() for s in self.plan.steps],
            "llm_calls": self.llm_calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "retries": self.retry_count,
            "recoveries": self.recovery_count,
            "replans": self.replan_count,
            "timings_ms": self.timings_ms,
            "total_ms": round(self.elapsed_ms(), 2),
        }
