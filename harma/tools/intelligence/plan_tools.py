"""
Harma Planning Tools — Phase 9

Includes:
  • plan_goal       — Creates a structured multi-step plan for a complex task (SAFE)
  • get_plan_status — Inspects active plan execution progress (SAFE)
"""

from __future__ import annotations

from typing import Any

from harma.intelligence.planner import AdvancedPlanner
from harma.tools.base import BaseTool, PermissionLevel, ToolResult


class PlanGoalTool(BaseTool):
    """Generate and inspect a structured plan for a user goal."""

    name = "plan_goal"
    description = (
        "Creates a structured, multi-step execution plan for a complex goal. "
        "Returns the plan steps, risk classification, and tools required. "
        "Supports dry_run to simulate steps without executing side effects."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "goal": {
                "type": "string",
                "description": "The high-level goal to plan and decompose into steps.",
            },
            "dry_run": {
                "type": "boolean",
                "description": "If true, simulates the plan without executing any side-effects.",
            },
        },
        "required": ["goal"],
    }

    def __init__(self, planner: AdvancedPlanner | None = None) -> None:
        self.planner = planner

    async def execute(self, goal: str, dry_run: bool = False, **kwargs: Any) -> ToolResult:
        if not self.planner:
            from harma.tools.registry import ToolRegistry
            self.planner = AdvancedPlanner(ToolRegistry())

        plan = self.planner.create_plan(goal=goal, dry_run=dry_run)
        if dry_run:
            plan = await self.planner.execute_plan(plan)

        return ToolResult(
            success=True,
            output=plan.summary(),
            data={
                "plan_id": plan.plan_id,
                "goal": plan.goal,
                "steps_count": len(plan.steps),
                "risk_level": plan.risk_level.value,
                "status": plan.status.value,
                "dry_run": plan.dry_run,
            },
        )


class GetPlanStatusTool(BaseTool):
    """Retrieve status and progress of the active plan."""

    name = "get_plan_status"
    description = "Returns current progress, completed steps, and active step description of the running plan."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, planner: AdvancedPlanner | None = None) -> None:
        self.planner = planner

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not self.planner:
            return ToolResult(
                success=True,
                output="No active plan currently executing.",
            )

        summary = self.planner.state.status_summary()
        return ToolResult(
            success=True,
            output=summary,
            data={
                "goal": self.planner.state.current_goal,
                "step_index": self.planner.state.current_step_index,
                "is_paused": self.planner.state.is_paused,
                "is_cancelled": self.planner.state.is_cancelled,
            },
        )
