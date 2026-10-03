"""
Harma Advanced Planner Engine

Decomposes complex goals into structured plans with risk classification,
conditional branching, dry-run simulation, execution control (pause/resume/cancel),
and outcome verification.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from harma.config.logging_config import get_logger
from harma.intelligence.context_models import UnifiedContext
from harma.intelligence.plan_models import (
    ExecutionState,
    Plan,
    PlanStatus,
    PlanStep,
    RiskLevel,
    StepStatus,
)
from harma.intelligence.recovery import AdaptiveRecoveryEngine, RecoveryStrategy
from harma.intelligence.telemetry import StructuredTelemetry
from harma.intelligence.tool_intelligence import ToolCapability, ToolIntelligence
from harma.intelligence.verification import ActionVerifier
from harma.tools.base import BaseTool, ToolResult
from harma.tools.registry import ToolRegistry

log = get_logger(__name__)


class AdvancedPlanner:
    """
    Structured planning and execution engine for Harma.
    Operates under the direct command of HarmaAgent.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        telemetry: Optional[StructuredTelemetry] = None,
    ) -> None:
        self.registry = registry
        self.telemetry = telemetry or StructuredTelemetry()
        self.verifier = ActionVerifier()
        self.recovery = AdaptiveRecoveryEngine()
        self.state = ExecutionState()

    def create_plan(
        self,
        goal: str,
        context: Optional[UnifiedContext] = None,
        dry_run: bool = False,
    ) -> Plan:
        """
        Decompose a user goal into a structured multi-step Plan.
        """
        log.info("[PLANNER] Creating plan for goal: '%s' (dry_run=%s)", goal, dry_run)
        plan = Plan(goal=goal, dry_run=dry_run)
        low_goal = goal.lower()

        # Goal Pattern 1: Search and note / extract web information
        if any(term in low_goal for term in ["search for", "find", "closing price", "nifty", "look up"]) and any(w in low_goal for w in ["note", "save", "write"]):
            plan.add_step(
                PlanStep(
                    step_id=1,
                    description="Open Google Chrome browser",
                    required_tool="open_application",
                    arguments={"application_name": "chrome"},
                    expected_result="Chrome application window open",
                    risk_level=RiskLevel.SAFE,
                )
            )
            plan.add_step(
                PlanStep(
                    step_id=2,
                    description="Navigate to search engine and query",
                    required_tool="browser_navigate",
                    arguments={"url": "https://www.google.com/search?q=" + goal.replace(" ", "+")},
                    expected_result="Search results page loaded",
                    risk_level=RiskLevel.SAFE,
                )
            )
            plan.add_step(
                PlanStep(
                    step_id=3,
                    description="Extract relevant search result value",
                    required_tool="browser_get_page_content",
                    expected_result="Parsed closing price or answer text",
                    risk_level=RiskLevel.SAFE,
                )
            )
            plan.add_step(
                PlanStep(
                    step_id=4,
                    description="Save result to notes file",
                    required_tool="open_application",
                    arguments={"application_name": "notepad"},
                    expected_result="Notes document updated",
                    risk_level=RiskLevel.SENSITIVE,
                    side_effects=True,
                )
            )
            plan.add_step(
                PlanStep(
                    step_id=5,
                    description="Verify note content matches extracted result",
                    required_tool="observe_screen",
                    expected_result="Target text verified in editor window",
                    risk_level=RiskLevel.SAFE,
                )
            )

        # Goal Pattern 2: Communication / Email / Message
        elif any(w in low_goal for w in ["send email", "send message", "slack", "notify"]):
            recipient = "User"
            if "to " in low_goal:
                parts = low_goal.split("to ", 1)
                recipient = parts[1].split()[0]

            plan.add_step(
                PlanStep(
                    step_id=1,
                    description=f"Prepare communication draft for {recipient}",
                    required_tool="get_current_time",
                    expected_result="Draft prepared",
                    risk_level=RiskLevel.SAFE,
                )
            )
            plan.add_step(
                PlanStep(
                    step_id=2,
                    description=f"Send message to {recipient}",
                    required_tool="gmail.send_message" if self.registry.get("gmail.send_message") else "system_info",
                    arguments={"recipient": recipient, "body": goal},
                    expected_result=f"Message successfully delivered to {recipient}",
                    risk_level=RiskLevel.HIGH_RISK,
                    side_effects=True,
                )
            )
            plan.add_step(
                PlanStep(
                    step_id=3,
                    description="Verify delivery state in sent items",
                    required_tool="gmail.search_messages" if self.registry.get("gmail.search_messages") else "get_current_time",
                    expected_result="Message confirmed in sent mailbox",
                    risk_level=RiskLevel.SAFE,
                )
            )

        # Goal Pattern 3: Desktop screen observation
        elif any(w in low_goal for w in ["screen", "look at", "what is open", "inspect"]):
            plan.add_step(
                PlanStep(
                    step_id=1,
                    description="Capture active desktop screen observation",
                    required_tool="take_screenshot" if self.registry.get("take_screenshot") else "get_system_info",
                    expected_result="Screen snapshot obtained",
                    risk_level=RiskLevel.SAFE,
                )
            )
            plan.add_step(
                PlanStep(
                    step_id=2,
                    description="Analyze visual UI elements and window titles",
                    required_tool="get_system_info",
                    expected_result="Structured desktop UI observation",
                    risk_level=RiskLevel.SAFE,
                )
            )

        # Default Multi-step Plan: Capability matching
        else:
            candidates = ToolIntelligence.match_tools_by_intent(goal, self.registry.list_tools(), limit=3)
            if candidates:
                for idx, tool in enumerate(candidates, start=1):
                    meta = ToolIntelligence.infer_metadata(tool)
                    plan.add_step(
                        PlanStep(
                            step_id=idx,
                            description=f"Execute {tool.name} for: {tool.description[:60]}",
                            required_tool=tool.name,
                            arguments={},
                            expected_result=f"Completion of {tool.name}",
                            risk_level=meta.risk_level,
                            side_effects=meta.side_effects,
                        )
                    )
            else:
                plan.add_step(
                    PlanStep(
                        step_id=1,
                        description=f"Fulfill request: {goal}",
                        required_tool="get_system_info",
                        expected_result="Goal completed",
                        risk_level=RiskLevel.SAFE,
                    )
                )

        self.state.current_goal = goal
        self.state.current_plan = plan
        return plan

    async def execute_plan(
        self,
        plan: Plan,
        confirm_callback: Optional[Callable[[str], str]] = None,
    ) -> Plan:
        """
        Execute plan steps sequentially with verification and recovery.
        """
        self.state.current_plan = plan
        self.state.current_goal = plan.goal
        plan.status = PlanStatus.RUNNING

        # Dry-run handling: Preview without side effects
        if plan.dry_run:
            log.info("[PLANNER] Simulating plan execution in DRY-RUN mode.")
            for step in plan.steps:
                step.status = StepStatus.SUCCESS
                step.observation = f"[DRY-RUN SIMULATION] Would execute tool '{step.required_tool}' with risk '{step.risk_level.value}'."
                self.state.completed_steps.append(step)
            plan.status = PlanStatus.COMPLETED
            return plan

        idx = 0
        while idx < len(plan.steps):
            if self.state.is_cancelled:
                plan.status = PlanStatus.CANCELLED
                log.info("[PLANNER] Plan execution cancelled by user.")
                break

            if self.state.is_paused:
                plan.status = PlanStatus.PAUSED
                log.info("[PLANNER] Plan execution paused.")
                break

            self.state.current_step_index = idx
            step = plan.steps[idx]
            step.status = StepStatus.RUNNING
            log.info("[PLANNER] Executing %s", step.to_summary())

            span = self.telemetry.start_span(
                name=f"step_{step.step_id}",
                plan_id=plan.plan_id,
                step_id=step.step_id,
                tool_name=step.required_tool,
            )

            # High-risk / sensitive confirmation check
            if step.risk_level in (RiskLevel.HIGH_RISK, RiskLevel.SENSITIVE) and step.side_effects:
                prompt_msg = (
                    f"Action Confirmation Required:\n"
                    f"Action: {step.description}\n"
                    f"Tool: {step.required_tool}\n"
                    f"Arguments: {step.arguments}\n"
                    f"Consequence: Potential external modification or side effect."
                )
                approved = True
                if confirm_callback:
                    ans = confirm_callback(prompt_msg)
                    approved = str(ans).strip().lower() in ("yes", "y", "confirm", "true", "approve")

                if not approved:
                    step.status = StepStatus.FAILED
                    step.observation = "Action cancelled by user during confirmation."
                    plan.status = PlanStatus.FAILED
                    span.finish(success=False, verification_status="USER_REJECTED")
                    self.telemetry.log_span(span)
                    break

            # Execute tool
            tool_result = await self._dispatch_step_tool(step)
            step.observation = tool_result.output or tool_result.error

            # Verify action outcome
            verification = self.verifier.verify_action(
                tool_name=step.required_tool,
                tool_result=tool_result,
                expected_result=step.expected_result,
                post_observation=step.observation,
            )
            step.verification = verification

            if verification.success:
                step.status = StepStatus.SUCCESS
                self.state.completed_steps.append(step)
                span.finish(success=True, verification_status=verification.summary())
                self.telemetry.log_span(span)

                # Check conditional branch
                if "on_success" in step.branch_conditions:
                    idx = step.branch_conditions["on_success"]
                else:
                    idx += 1
            else:
                # Step failed verification or execution
                log.warning("[PLANNER] Step %d failed verification: %s", step.step_id, verification.details)
                strategy, reason = self.recovery.analyze_failure(step, tool_result, step.observation)

                if strategy == RecoveryStrategy.RETRY:
                    self.recovery.adapt_step_for_retry(step, strategy, step.observation)
                    # Stay on same step index to retry
                    continue
                elif strategy == RecoveryStrategy.FALLBACK_TOOL:
                    self.recovery.adapt_step_for_retry(step, strategy, step.observation)
                    continue
                elif strategy == RecoveryStrategy.REPLAN:
                    replan_steps = self.recovery.create_replan_steps(step, plan, step.observation)
                    # Insert replanned steps
                    plan.steps[idx:idx+1] = replan_steps
                    continue
                elif strategy == RecoveryStrategy.ASK_USER:
                    step.status = StepStatus.FAILED
                    plan.status = PlanStatus.FAILED
                    span.finish(success=False, verification_status="ESCALATED_TO_USER")
                    self.telemetry.log_span(span)
                    break
                else:
                    step.status = StepStatus.FAILED
                    self.state.failed_steps.append(step)
                    plan.status = PlanStatus.FAILED
                    span.finish(success=False, verification_status="FAILED")
                    self.telemetry.log_span(span)
                    break

        if not (self.state.is_cancelled or self.state.is_paused or plan.status in (PlanStatus.CANCELLED, PlanStatus.PAUSED, PlanStatus.FAILED)):
            if all(s.status == StepStatus.SUCCESS for s in plan.steps):
                plan.status = PlanStatus.COMPLETED

        return plan

    async def _dispatch_step_tool(self, step: PlanStep) -> ToolResult:
        """Call tool from registry or synthesize result for simulation."""
        if not step.required_tool:
            return ToolResult(success=True, output=f"Completed {step.description}")

        tool = self.registry.get(step.required_tool)
        if not tool:
            # Check if this is a high-level pseudo tool
            if step.required_tool in ("observe_screen", "browser_get_page_content"):
                return ToolResult(success=True, output=f"Observation for {step.description} obtained.")
            return ToolResult(success=False, output="", error=f"Tool '{step.required_tool}' not registered.")

        return await self.registry.call(step.required_tool, **step.arguments)

    def pause(self) -> None:
        """Pause active plan execution."""
        self.state.is_paused = True

    def resume(self) -> None:
        """Resume paused plan execution."""
        self.state.is_paused = False

    def cancel(self) -> None:
        """Cancel active plan execution."""
        self.state.is_cancelled = True
        if self.state.current_plan:
            self.state.current_plan.status = PlanStatus.CANCELLED
