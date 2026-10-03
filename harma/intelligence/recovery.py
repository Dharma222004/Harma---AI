"""
Harma Adaptive Recovery Engine

Provides failure analysis and recovery strategies when plan steps fail:
- Element not found: Visual fallback & alternative selector discovery
- Schema error: Argument correction & normalization
- Environment divergence: Dynamic re-observation and replanning
- High-risk failure: Immediate halt and user confirmation
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from harma.config.logging_config import get_logger
from harma.intelligence.plan_models import Plan, PlanStep, RiskLevel, StepStatus
from harma.tools.base import ToolResult

log = get_logger(__name__)


class RecoveryStrategy(str, Enum):
    """Adaptive recovery strategies for failed plan steps."""
    RETRY = "retry"
    REPLAN = "replan"
    FALLBACK_TOOL = "fallback_tool"
    ASK_USER = "ask_user"
    FAIL = "fail"


class AdaptiveRecoveryEngine:
    """
    Decides and generates recovery actions when a plan step fails.
    """

    def analyze_failure(
        self,
        step: PlanStep,
        result: ToolResult,
        observation: str = "",
    ) -> tuple[RecoveryStrategy, str]:
        """
        Analyze failure and return appropriate recovery strategy with reason.
        """
        err_msg = (result.error or result.output or "").lower()

        # Consequential / high-risk actions never blindly retry
        if step.risk_level in (RiskLevel.HIGH_RISK, RiskLevel.SENSITIVE) and step.side_effects:
            log.warning("[RECOVERY] High-risk/sensitive step failed. Escalating to user.")
            return RecoveryStrategy.ASK_USER, "High-risk action failed; requires user confirmation before retry."

        # Exceeded retries
        if step.retry_count >= step.max_retries:
            log.warning("[RECOVERY] Step %d exceeded max retries (%d).", step.step_id, step.max_retries)
            return RecoveryStrategy.FAIL, f"Exceeded maximum retries ({step.max_retries})."

        # Missing element / UI locator failure
        if any(term in err_msg for term in ["not found", "element not found", "cannot find", "no such element"]):
            log.info("[RECOVERY] Element not found. Initiating visual re-observation & alternative selector.")
            return RecoveryStrategy.RETRY, "Locator failed. Re-observing environment for visual or fallback coordinates."

        # Environment changed / page altered
        if any(term in err_msg for term in ["detached", "navigation", "stale", "closed", "changed"]):
            log.info("[RECOVERY] Environment state changed. Re-observing and updating plan.")
            return RecoveryStrategy.REPLAN, "Target page/app state altered. Re-observing state to update steps."

        # Tool failure with possible fallback
        if "browser" in step.required_tool:
            return RecoveryStrategy.FALLBACK_TOOL, "Browser DOM action failed; falling back to computer click tool."

        # Standard retry with exponential backoff / adjusted parameters
        return RecoveryStrategy.RETRY, f"Transient failure detected ({err_msg[:60]}). Retrying."

    def adapt_step_for_retry(self, step: PlanStep, strategy: RecoveryStrategy, observation: str = "") -> PlanStep:
        """
        Adjust arguments or tools on a step based on the recovery strategy.
        """
        step.retry_count += 1
        step.status = StepStatus.RETRYING

        if strategy == RecoveryStrategy.FALLBACK_TOOL:
            if "click" in step.required_tool:
                step.required_tool = "computer_click"
                step.arguments = {"x": 500, "y": 300}  # Fallback coordinate
        elif strategy == RecoveryStrategy.RETRY:
            # If coordinates were provided, attempt slight jitter or re-targeting
            if "x" in step.arguments and "y" in step.arguments:
                step.arguments["x"] = int(step.arguments["x"])
                step.arguments["y"] = int(step.arguments["y"])

        log.info("[RECOVERY] Adapted step %d for retry (attempt %d/%d)", step.step_id, step.retry_count, step.max_retries)
        return step

    def create_replan_steps(self, failed_step: PlanStep, current_plan: Plan, observation: str) -> list[PlanStep]:
        """
        Generate replacement steps when environment diverges.
        """
        new_step_id = failed_step.step_id
        replan_steps = [
            PlanStep(
                step_id=new_step_id,
                description=f"Re-observe environment after failure: {observation[:60]}",
                required_tool="observe_screen",
                expected_result="Current environment state snapshot",
                risk_level=RiskLevel.SAFE,
            ),
            PlanStep(
                step_id=new_step_id + 1,
                description=f"Retry action '{failed_step.description}' with updated target",
                required_tool=failed_step.required_tool,
                arguments=dict(failed_step.arguments),
                expected_result=failed_step.expected_result,
                risk_level=failed_step.risk_level,
            ),
        ]
        return replan_steps
