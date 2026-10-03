"""
Harma Runtime V3 — Experience Models & Confidence (spec §9, §13, §37–39)

Experience is structured, verified knowledge — never raw transcripts.
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


class ProcedureStatus(str, Enum):
    CANDIDATE = "candidate"     # verified at least once, still on probation
    TRUSTED   = "trusted"       # repeatedly verified; eligible for zero-LLM reuse
    DISABLED  = "disabled"      # repeatedly failing; must be relearned
    UNVERIFIED = "unverified"   # executed but never verified — never reused directly


class ExperienceSource(str, Enum):
    VERIFIED_EXECUTION = "verified_execution"
    UNVERIFIED_EXECUTION = "unverified_execution"
    EXPLICIT_USER_CORRECTION = "explicit_user_correction"
    EXPLICIT_USER_FEEDBACK = "explicit_user_feedback"
    OBSERVED_ENVIRONMENT = "observed_environment"
    ANALYZER = "experience_analyzer"


# ── Tunables ──────────────────────────────────────────────────────────────────

TRUST_MIN_VERIFIED_SUCCESSES = 2
TRUST_MIN_SUCCESS_RATE = 0.75
TRUST_MIN_CONFIDENCE = 0.6
DISABLE_CONSECUTIVE_FAILURES = 3
DISABLE_MAX_SUCCESS_RATE = 0.4
RECENCY_HALF_LIFE_DAYS = 30.0
# Candidates (one verified success) may be reused on probation — with full verification and
# LLM adaptation on mismatch — but only when the procedure is not high-risk.
CANDIDATE_REUSE_MIN_CONFIDENCE = 0.4


def _now() -> float:
    return time.time()


@dataclass
class Episode:
    """Episodic experience — what happened (compact, not a transcript)."""
    run_id: str
    goal: str
    task_type: str
    strategy: str
    template: str = ""
    procedure_id: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)   # tool, args (redacted), status, verification
    errors: list[dict[str, Any]] = field(default_factory=list)
    outcome: str = ""                                            # verified | unverified | failed | cancelled | answered
    duration_ms: float = 0.0
    llm_calls: int = 0
    tool_calls: int = 0
    environment: dict[str, Any] = field(default_factory=dict)
    episode_id: str = field(default_factory=lambda: f"ep_{uuid.uuid4().hex[:10]}")
    created_at: float = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Procedure:
    """Procedural experience — how to perform a task pattern."""
    task_pattern: str                                  # e.g. "open_application>type_text"
    steps: list[dict[str, Any]]                         # [{"tool":..., "arguments": {... "{s0}" ...}}]
    templates: list[str] = field(default_factory=list)  # parameterised request templates
    slots: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    preconditions: dict[str, Any] = field(default_factory=dict)
    success_criteria: list[str] = field(default_factory=list)
    verification_strategy: list[str] = field(default_factory=list)
    known_failure_modes: list[dict[str, Any]] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)
    risk_level: str = "low"

    status: ProcedureStatus = ProcedureStatus.CANDIDATE
    confidence: float = 0.0
    usage_count: int = 0
    success_count: int = 0          # verified successes only
    unverified_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    user_confirmations: int = 0
    user_rejections: int = 0

    avg_latency_ms: float = 0.0
    avg_llm_calls: float = 0.0
    avg_tool_calls: float = 0.0

    source: str = ExperienceSource.VERIFIED_EXECUTION.value
    procedure_id: str = field(default_factory=lambda: f"proc_{uuid.uuid4().hex[:10]}")
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    last_used_at: float = 0.0
    last_success_at: float = 0.0

    # ── Derived metrics ───────────────────────────────────────────────────────

    @property
    def success_rate(self) -> float:
        attempts = self.success_count + self.failure_count
        return self.success_count / attempts if attempts else 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Procedure":
        d = dict(d)
        d["status"] = ProcedureStatus(d.get("status", "candidate"))
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class FailureExperience:
    """Failure experience — what to avoid."""
    task_pattern: str
    failed_strategy: str
    failure_type: str
    reason: str
    context: dict[str, Any] = field(default_factory=dict)
    observed_state: dict[str, Any] = field(default_factory=dict)
    better_strategy: str = ""
    procedure_id: str = ""
    template: str = ""
    confidence: float = 0.5
    occurrences: int = 1
    failure_id: str = field(default_factory=lambda: f"fail_{uuid.uuid4().hex[:10]}")
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Correction:
    """Correction / preference experience — what the user explicitly asked for."""
    kind: str                        # prefer | avoid | require_confirmation | reject_last | confirm_last
    subject: str = ""                # e.g. "edge"
    replaces: str = ""               # e.g. "chrome"
    scope: str = "global"
    previous_behavior: str = ""
    user_statement: str = ""
    source: str = ExperienceSource.EXPLICIT_USER_CORRECTION.value
    confidence: float = 0.95
    active: bool = True
    correction_id: str = field(default_factory=lambda: f"corr_{uuid.uuid4().hex[:10]}")
    created_at: float = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SemanticFact:
    """Semantic knowledge — e.g. an application or device known to be available."""
    category: str                    # application | device | integration | capability | preference
    key: str
    value: str = ""
    confidence: float = 0.6
    source: str = ExperienceSource.OBSERVED_ENVIRONMENT.value
    updated_at: float = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Confidence model ──────────────────────────────────────────────────────────

def recency_factor(last_success_at: float, now: Optional[float] = None) -> float:
    """1.0 for fresh experience, decaying towards 0 with a 30-day half-life."""
    if not last_success_at:
        return 0.0
    days = max(0.0, ((now or _now()) - last_success_at) / 86400.0)
    return math.pow(0.5, days / RECENCY_HALF_LIFE_DAYS)


def compute_confidence(proc: Procedure, now: Optional[float] = None) -> float:
    """
    Confidence = Bayesian success estimate × repetition cap × recency, adjusted by user feedback.

    - Unverified executions contribute nothing (never reinforce).
    - A single verified success yields at most ~0.55 (probation), not high confidence.
    - Failures and user rejections pull confidence down quickly.
    """
    s, f = proc.success_count, proc.failure_count + 2 * proc.user_rejections
    if s == 0:
        return 0.0
    bayes = (s + 1.0) / (s + f + 2.0)
    repetition_cap = 1.0 - math.pow(0.55, s)            # 1→0.45, 2→0.70, 3→0.83, 5→0.95
    recency = 0.6 + 0.4 * recency_factor(proc.last_success_at, now)
    feedback = min(0.15, 0.05 * proc.user_confirmations)
    conf = bayes * (0.35 + 0.65 * repetition_cap) * recency + feedback
    return round(max(0.0, min(0.99, conf)), 3)


def evaluate_status(proc: Procedure) -> ProcedureStatus:
    """Promotion / demotion rules (spec §38, §39)."""
    if proc.success_count == 0:
        return ProcedureStatus.UNVERIFIED
    if proc.consecutive_failures >= DISABLE_CONSECUTIVE_FAILURES:
        return ProcedureStatus.DISABLED
    attempts = proc.success_count + proc.failure_count
    if attempts >= 4 and proc.success_rate < DISABLE_MAX_SUCCESS_RATE:
        return ProcedureStatus.DISABLED
    if proc.user_rejections > proc.user_confirmations and proc.consecutive_failures:
        return ProcedureStatus.CANDIDATE
    if (
        proc.success_count >= TRUST_MIN_VERIFIED_SUCCESSES
        and proc.success_rate >= TRUST_MIN_SUCCESS_RATE
        and proc.confidence >= TRUST_MIN_CONFIDENCE
        and proc.consecutive_failures == 0
    ):
        return ProcedureStatus.TRUSTED
    return ProcedureStatus.CANDIDATE


def refresh(proc: Procedure, now: Optional[float] = None) -> Procedure:
    """Recompute confidence and status in place."""
    proc.confidence = compute_confidence(proc, now)
    proc.status = evaluate_status(proc)
    proc.updated_at = now or _now()
    return proc
