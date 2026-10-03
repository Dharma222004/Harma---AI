"""
Harma Plan Models & Execution State

Defines structured plan representations, risk classifications, step definitions,
and active execution state for multi-step reasoning.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from harma.intelligence.verification import VerificationResult


class PlanStatus(str, Enum):
    """Execution state of a plan."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    """Execution state of an individual plan step."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class RiskLevel(str, Enum):
    """
    Action risk classification mapped to Harma permission system:
      SAFE       — Read-only, informational, low risk
      LOW_RISK   — Opening apps, navigating
      SENSITIVE  — Reading private emails/documents, form inputs
      HIGH_RISK  — Sending messages, deleting data, purchases, modifications
    """
    SAFE = "safe"
    LOW_RISK = "low_risk"
    SENSITIVE = "sensitive"
    HIGH_RISK = "high_risk"


@dataclass
class PlanStep:
    """An individual step in a structured plan."""
    step_id: int
    description: str
    required_tool: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    expected_result: str = ""
    success_condition: str = ""
    risk_level: RiskLevel = RiskLevel.SAFE
    status: StepStatus = StepStatus.PENDING
    retry_count: int = 0
    max_retries: int = 3
    observation: str = ""
    verification: Optional[VerificationResult] = None
    branch_conditions: dict[str, int] = field(default_factory=dict)
    side_effects: bool = False

    def to_summary(self) -> str:
        tool_str = f" [{self.required_tool}]" if self.required_tool else ""
        return f"Step {self.step_id}: {self.description}{tool_str} ({self.status.value.upper()})"


@dataclass
class Plan:
    """
    Structured plan encapsulating a multi-step workflow.
    """
    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    success_criteria: str = ""
    failure_policy: str = "stop"  # stop | retry | fallback | ask_user
    risk_level: RiskLevel = RiskLevel.SAFE
    status: PlanStatus = PlanStatus.PENDING
    dry_run: bool = False
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: float = field(default_factory=time.time)

    def add_step(self, step: PlanStep) -> None:
        self.steps.append(step)
        if step.risk_level == RiskLevel.HIGH_RISK:
            self.risk_level = RiskLevel.HIGH_RISK
        elif step.risk_level == RiskLevel.SENSITIVE and self.risk_level != RiskLevel.HIGH_RISK:
            self.risk_level = RiskLevel.SENSITIVE

    def summary(self) -> str:
        lines = [
            f"Plan [{self.plan_id}] Goal: {self.goal}",
            f"Status: {self.status.value.upper()} | Risk: {self.risk_level.value.upper()} | Dry Run: {self.dry_run}",
            "Steps:",
        ]
        for s in self.steps:
            lines.append(f"  {s.to_summary()}")
        return "\n".join(lines)


@dataclass
class ExecutionState:
    """
    Active execution state tracking for the agent and CLI.
    """
    current_goal: str = ""
    current_plan: Optional[Plan] = None
    current_step_index: int = 0
    completed_steps: list[PlanStep] = field(default_factory=list)
    failed_steps: list[PlanStep] = field(default_factory=list)
    pending_confirmation: Optional[dict[str, Any]] = None
    last_observation: str = ""
    is_paused: bool = False
    is_cancelled: bool = False

    def reset(self) -> None:
        self.current_goal = ""
        self.current_plan = None
        self.current_step_index = 0
        self.completed_steps.clear()
        self.failed_steps.clear()
        self.pending_confirmation = None
        self.last_observation = ""
        self.is_paused = False
        self.is_cancelled = False

    def status_summary(self) -> str:
        if not self.current_plan:
            return "No active plan currently executing."
        total = len(self.current_plan.steps)
        current = min(self.current_step_index + 1, total)
        current_step_desc = (
            self.current_plan.steps[self.current_step_index].description
            if self.current_step_index < total
            else "Finished"
        )
        status_text = "PAUSED" if self.is_paused else ("CANCELLED" if self.is_cancelled else self.current_plan.status.value.upper())
        return (
            f"Goal: {self.current_goal}\n"
            f"Status: {status_text}\n"
            f"Progress: Step {current}/{total}\n"
            f"Current Action: {current_step_desc}"
        )
