"""
Harma Task Tools

Registers all proactive task management tools into Harma's Tool Registry.
Fully integrated with the existing Permission System, ToolResult format,
and Agent Core.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from harma.config.logging_config import get_logger
from harma.tasks.exceptions import TaskError
from harma.tasks.manager import TaskManager, get_task_manager
from harma.tasks.models import AutonomyLevel, TaskStatus, TaskTrigger, TriggerType
from harma.tools.base import BaseTool, PermissionLevel, ToolResult

log = get_logger(__name__)


class CreateTaskTool(BaseTool):
    """Schedule or create a proactive autonomous task."""

    name = "tasks.create"
    description = (
        "Create and schedule a proactive background task. Supports one-time, recurring "
        "(daily/weekly), interval, and conditional triggers."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Short human-readable title for the task."},
            "objective": {"type": "string", "description": "Clear instruction of what the agent should do when triggered."},
            "trigger_type": {
                "type": "string",
                "enum": ["one_time", "recurring", "interval", "conditional"],
                "default": "one_time",
                "description": "Trigger schedule type.",
            },
            "run_at": {"type": "number", "description": "Epoch timestamp for one_time trigger."},
            "daily_time": {"type": "string", "description": "Time in HH:MM format (e.g. '09:00') for recurring triggers."},
            "weekly_days": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Days of week (0=Mon, 6=Sun) for weekly recurring triggers.",
            },
            "interval_seconds": {"type": "number", "description": "Seconds between runs for interval triggers."},
            "condition_query": {"type": "string", "description": "Condition description or URL for conditional triggers."},
            "autonomy_level": {
                "type": "string",
                "enum": ["manual", "reminder", "read_only", "low_risk", "consequential"],
                "default": "read_only",
                "description": "Autonomy level constraint.",
            },
            "allowed_tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tool allowlist. If empty, allows tools matching autonomy level.",
            },
            "timezone": {"type": "string", "default": "UTC", "description": "Timezone for task."},
        },
        "required": ["name", "objective"],
    }

    def __init__(self, manager: Optional[TaskManager] = None) -> None:
        self.manager = manager or get_task_manager()

    async def execute(
        self,
        name: str,
        objective: str,
        trigger_type: str = "one_time",
        run_at: Optional[float] = None,
        daily_time: Optional[str] = None,
        weekly_days: Optional[list[int]] = None,
        interval_seconds: Optional[float] = None,
        condition_query: Optional[str] = None,
        autonomy_level: str = "read_only",
        allowed_tools: Optional[list[str]] = None,
        timezone: str = "UTC",
        **kwargs: Any,
    ) -> ToolResult:
        try:
            tt = TriggerType(trigger_type)
            # Default run_at to 60s from now if not given for one_time
            if tt == TriggerType.ONE_TIME and run_at is None:
                run_at = time.time() + 60.0

            trigger = TaskTrigger(
                trigger_type=tt,
                run_at=run_at,
                daily_time=daily_time,
                weekly_days=weekly_days or [],
                interval_seconds=interval_seconds,
                condition_query=condition_query,
            )
            auton = AutonomyLevel(autonomy_level)

            task = await self.manager.create_task(
                name=name,
                objective=objective,
                trigger=trigger,
                autonomy_level=auton,
                allowed_tools=allowed_tools,
                timezone=timezone,
            )

            return ToolResult(
                success=True,
                output=f"Task '{task.name}' created and scheduled successfully (ID: {task.id}).",
                data=task.to_dict(),
            )
        except TaskError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)
        except Exception as exc:
            log.error("Error creating task: %s", exc)
            return ToolResult(success=False, output="Failed to create task.", error="CREATE_TASK_ERROR")


class ListTasksTool(BaseTool):
    """List scheduled and active tasks."""

    name = "tasks.list"
    description = "List all scheduled, active, or paused proactive tasks."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["draft", "scheduled", "running", "paused", "completed", "failed", "cancelled"],
                "description": "Optional status filter.",
            }
        },
    }

    def __init__(self, manager: Optional[TaskManager] = None) -> None:
        self.manager = manager or get_task_manager()

    async def execute(self, status: Optional[str] = None, **kwargs: Any) -> ToolResult:
        try:
            st = TaskStatus(status) if status else None
            tasks = self.manager.list_tasks(status=st)
            if not tasks:
                return ToolResult(success=True, output="No tasks found.", data={"tasks": []})

            lines = [
                f"- [{t.id[:10]}] {t.name} ({t.status.value}) | Next: {t.next_run_at} | Objective: {t.objective[:60]}"
                for t in tasks
            ]
            return ToolResult(
                success=True,
                output=f"Active tasks ({len(tasks)}):\n" + "\n".join(lines),
                data={"tasks": [t.to_dict() for t in tasks]},
            )
        except Exception as exc:
            return ToolResult(success=False, output=str(exc), error="LIST_TASKS_ERROR")


class GetTaskTool(BaseTool):
    """Get details of a specific task."""

    name = "tasks.get"
    description = "Retrieve full details and schedule configuration of a task by ID."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {"task_id": {"type": "string", "description": "The task ID."}},
        "required": ["task_id"],
    }

    def __init__(self, manager: Optional[TaskManager] = None) -> None:
        self.manager = manager or get_task_manager()

    async def execute(self, task_id: str, **kwargs: Any) -> ToolResult:
        try:
            task = self.manager.get_task(task_id)
            return ToolResult(
                success=True,
                output=f"Task {task.id}: {task.name} ({task.status.value})\nObjective: {task.objective}\nNext run: {task.next_run_at}",
                data=task.to_dict(),
            )
        except TaskError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


class PauseTaskTool(BaseTool):
    """Pause a scheduled task."""

    name = "tasks.pause"
    description = "Pause a scheduled task so it will not trigger automatically."
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {"task_id": {"type": "string", "description": "The task ID."}},
        "required": ["task_id"],
    }

    def __init__(self, manager: Optional[TaskManager] = None) -> None:
        self.manager = manager or get_task_manager()

    async def execute(self, task_id: str, **kwargs: Any) -> ToolResult:
        try:
            task = self.manager.pause_task(task_id)
            return ToolResult(success=True, output=f"Task '{task.name}' paused.", data=task.to_dict())
        except TaskError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


class ResumeTaskTool(BaseTool):
    """Resume a paused task."""

    name = "tasks.resume"
    description = "Resume a paused task, rescheduling its next execution."
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {"task_id": {"type": "string", "description": "The task ID."}},
        "required": ["task_id"],
    }

    def __init__(self, manager: Optional[TaskManager] = None) -> None:
        self.manager = manager or get_task_manager()

    async def execute(self, task_id: str, **kwargs: Any) -> ToolResult:
        try:
            task = self.manager.resume_task(task_id)
            return ToolResult(success=True, output=f"Task '{task.name}' resumed.", data=task.to_dict())
        except TaskError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


class CancelTaskTool(BaseTool):
    """Cancel a task."""

    name = "tasks.cancel"
    description = "Cancel a scheduled or active task."
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {"task_id": {"type": "string", "description": "The task ID."}},
        "required": ["task_id"],
    }

    def __init__(self, manager: Optional[TaskManager] = None) -> None:
        self.manager = manager or get_task_manager()

    async def execute(self, task_id: str, **kwargs: Any) -> ToolResult:
        try:
            task = self.manager.cancel_task(task_id)
            return ToolResult(success=True, output=f"Task '{task.name}' cancelled.", data=task.to_dict())
        except TaskError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


class RunTaskNowTool(BaseTool):
    """Immediately execute a task."""

    name = "tasks.run_now"
    description = "Immediately trigger an execution of a task without waiting for its scheduled time."
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {"task_id": {"type": "string", "description": "The task ID."}},
        "required": ["task_id"],
    }

    def __init__(self, manager: Optional[TaskManager] = None) -> None:
        self.manager = manager or get_task_manager()

    async def execute(self, task_id: str, **kwargs: Any) -> ToolResult:
        try:
            history = await self.manager.run_task_now(task_id)
            return ToolResult(
                success=(history.status == "success"),
                output=f"Task executed with status '{history.status}': {history.summary or history.error}",
                data=history.to_dict(),
            )
        except TaskError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


class TaskHistoryTool(BaseTool):
    """View task execution history."""

    name = "tasks.history"
    description = "View execution audit history for all tasks or a specific task."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Optional task ID to filter history."},
            "limit": {"type": "integer", "default": 20, "description": "Max entries to return."},
        },
    }

    def __init__(self, manager: Optional[TaskManager] = None) -> None:
        self.manager = manager or get_task_manager()

    async def execute(self, task_id: Optional[str] = None, limit: int = 20, **kwargs: Any) -> ToolResult:
        try:
            histories = self.manager.get_history(task_id=task_id, limit=limit)
            if not histories:
                return ToolResult(success=True, output="No execution history found.", data={"history": []})

            lines = [
                f"- [{h.execution_id[:8]}] task={h.task_id[:8]} status={h.status} tools={h.tools_used} summary={h.summary[:50]}"
                for h in histories
            ]
            return ToolResult(
                success=True,
                output=f"Execution History ({len(histories)} entries):\n" + "\n".join(lines),
                data={"history": [h.to_dict() for h in histories]},
            )
        except Exception as exc:
            return ToolResult(success=False, output=str(exc), error="HISTORY_ERROR")


class DeleteTaskTool(BaseTool):
    """Delete a task."""

    name = "tasks.delete"
    description = "Permanently remove a task and its schedule."
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {"task_id": {"type": "string", "description": "The task ID."}},
        "required": ["task_id"],
    }

    def __init__(self, manager: Optional[TaskManager] = None) -> None:
        self.manager = manager or get_task_manager()

    async def execute(self, task_id: str, **kwargs: Any) -> ToolResult:
        try:
            success = self.manager.delete_task(task_id)
            return ToolResult(
                success=success,
                output=f"Task {task_id} deleted." if success else f"Task {task_id} not found.",
            )
        except Exception as exc:
            return ToolResult(success=False, output=str(exc), error="DELETE_ERROR")


def get_task_tools(manager: Optional[TaskManager] = None) -> list[BaseTool]:
    """Return instantiated list of all Phase 7 task management tools."""
    mgr = manager or get_task_manager()
    return [
        CreateTaskTool(mgr),
        ListTasksTool(mgr),
        GetTaskTool(mgr),
        PauseTaskTool(mgr),
        ResumeTaskTool(mgr),
        CancelTaskTool(mgr),
        RunTaskNowTool(mgr),
        TaskHistoryTool(mgr),
        DeleteTaskTool(mgr),
    ]
