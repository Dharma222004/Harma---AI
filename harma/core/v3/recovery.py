"""
Harma Runtime V3 — Failure classification & Recovery policy (spec §23, §24, §30, §59)

    ACTION → FAILURE → CLASSIFY → known recovery?  ├─ yes → RETRY (deterministic, bounded)
                                                  └─ no  → LLM REPLAN of remaining steps only

Never blindly retries consequential actions, never fails on a single transient error and
never runs indefinitely.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class FailureClass(str, Enum):
    TRANSIENT = "transient"
    INVALID_ARGUMENT = "invalid_argument"
    ELEMENT_NOT_FOUND = "element_not_found"
    TIMEOUT = "timeout"
    AUTHENTICATION = "authentication"
    PERMISSION_DENIED = "permission_denied"
    RESOURCE_UNAVAILABLE = "resource_unavailable"
    ENVIRONMENT_CHANGED = "environment_changed"
    UNKNOWN = "unknown"
    USER_CANCELLED = "user_cancelled"
    VERIFICATION_FAILED = "verification_failed"
    LOOP_DETECTED = "loop_detected"
    DUPLICATE_SIDE_EFFECT_RISK = "duplicate_side_effect_risk"


def classify_error_text(err_text: str) -> FailureClass:
    """Keyword taxonomy ported from the existing engine (kept identical for parity)."""
    low = (err_text or "").lower()
    if any(w in low for w in ["invalid argument", "required argument", "unexpected keyword", "type error",
                               "missing required"]):
        return FailureClass.INVALID_ARGUMENT
    if any(w in low for w in ["timeout", "timed out", "deadline"]):
        return FailureClass.TIMEOUT
    if any(w in low for w in ["not found", "cannot find", "no such", "missing", "not available", "unknown tool"]):
        return FailureClass.ELEMENT_NOT_FOUND
    if any(w in low for w in ["denied", "permission", "unauthorized", "forbidden"]):
        return FailureClass.PERMISSION_DENIED
    if any(w in low for w in ["auth", "login", "password", "token expired"]):
        return FailureClass.AUTHENTICATION
    if any(w in low for w in ["stale", "detached", "closed", "navigated", "environment"]):
        return FailureClass.ENVIRONMENT_CHANGED
    if any(w in low for w in ["connection", "network", "reset", "busy", "temporary", "retry", "unavailable"]):
        return FailureClass.TRANSIENT
    return FailureClass.UNKNOWN


_AMBIGUOUS_FOR_SIDE_EFFECTS = {FailureClass.TIMEOUT, FailureClass.UNKNOWN, FailureClass.TRANSIENT}
_NEVER_RECOVER = {FailureClass.PERMISSION_DENIED, FailureClass.AUTHENTICATION, FailureClass.USER_CANCELLED,
                  FailureClass.DUPLICATE_SIDE_EFFECT_RISK}


@dataclass
class RecoveryDecision:
    action: str                     # retry | replan | fail
    failure: FailureClass
    reason: str
    backoff_s: float = 0.0


class RecoveryPolicy:
    def __init__(self, max_retries: int = 2, max_replans: int = 2, can_reason: bool = True) -> None:
        self.max_retries = max_retries
        self.max_replans = max_replans
        self.can_reason = can_reason

    def decide(self, *, failure: FailureClass, step_attempts: int, replan_count: int,
               consequential: bool, action_executed: bool, ambiguous: bool = False,
               message: str = "") -> RecoveryDecision:
        if failure in _NEVER_RECOVER:
            return RecoveryDecision("fail", failure, message or failure.value)

        # A consequential action that executed but ended ambiguously may already have taken effect.
        if consequential and action_executed and ambiguous:
            return RecoveryDecision("fail", FailureClass.DUPLICATE_SIDE_EFFECT_RISK,
                                    "the action may already have taken effect, so I did not repeat it")

        if failure in (FailureClass.TRANSIENT, FailureClass.TIMEOUT) and step_attempts <= self.max_retries:
            return RecoveryDecision("retry", failure, message, backoff_s=min(2.0, 0.25 * (2 ** (step_attempts - 1))))

        if self.can_reason and replan_count < self.max_replans:
            return RecoveryDecision("replan", failure, message)

        return RecoveryDecision("fail", failure, message or "recovery exhausted")


def failure_message(failure: FailureClass | str, tool: str = "", detail: str = "") -> str:
    """Deterministic, user-facing explanation (spec §52)."""
    f = FailureClass(failure) if not isinstance(failure, FailureClass) else failure
    t = f"'{tool}'" if tool else "the action"
    if f == FailureClass.PERMISSION_DENIED:
        return f"the permission policy denied {t}"
    if f == FailureClass.USER_CANCELLED:
        return f"you declined the confirmation for {t}"
    if f == FailureClass.AUTHENTICATION:
        return f"{t} requires you to sign in first"
    if f == FailureClass.DUPLICATE_SIDE_EFFECT_RISK:
        return f"{t} may already have taken effect, so I did not repeat it — please check before retrying"
    if f == FailureClass.LOOP_DETECTED:
        return f"I kept repeating {t} without making progress"
    if f == FailureClass.VERIFICATION_FAILED:
        return f"{t} ran, but the expected result could not be confirmed" + (f" ({detail})" if detail else "")
    if f == FailureClass.ELEMENT_NOT_FOUND:
        return f"the target for {t} could not be found" + (f" ({detail})" if detail else "")
    if f == FailureClass.TIMEOUT:
        return f"{t} timed out"
    return (detail or f"{t} failed")[:240]


def error_payload(failure: FailureClass, message: str, **extra: Any) -> dict[str, Any]:
    return {"type": failure.value, "message": (message or "")[:500], **extra}


def parse_failure(value: Optional[str]) -> FailureClass:
    try:
        return FailureClass(value or "unknown")
    except ValueError:
        return FailureClass.UNKNOWN
