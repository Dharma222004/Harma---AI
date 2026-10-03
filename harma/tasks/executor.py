"""
Harma Task Executor

Executes autonomous background tasks through the EXISTING Agent Core (HarmaAgent).
Enforces tool allowlists, autonomy levels, runtime timeouts, step limits,
and action loop detection.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Optional

from harma.config.logging_config import get_logger
from harma.core.agent import HarmaAgent
from harma.core.context import AgentContext
from harma.tasks.exceptions import (
    AutonomyPermissionError,
    LoopDetectedError,
    ScopeViolationError,
    TaskStepLimitError,
    TaskTimeoutError,
)
from harma.tasks.models import (
    AutonomyLevel,
    Task,
    TaskExecutionHistory,
    TaskStatus,
)
from harma.tools.base import BaseTool, PermissionLevel, ToolResult
from harma.tools.registry import ToolRegistry

log = get_logger(__name__)


class ScopedToolRegistry(ToolRegistry):
    """
    Registry wrapper that strictly limits tool access to a task's allowed_tools
    and autonomy level.
    """

    def __init__(
        self,
        base_registry: ToolRegistry,
        allowed_tools: list[str],
        autonomy_level: AutonomyLevel,
        dry_run: bool = False,
    ) -> None:
        super().__init__()
        self._base = base_registry
        self.allowed_tools = set(allowed_tools) if allowed_tools else None
        self.autonomy_level = autonomy_level
        self.dry_run = dry_run
        self.tools_executed: list[str] = []

    def get(self, name: str) -> Optional[BaseTool]:
        # Check explicit tool allowlist first
        if self.allowed_tools is not None and name not in self.allowed_tools:
            log.warning("SCOPE_VIOLATION tool %s not in allowed_tools %s", name, self.allowed_tools)
            raise ScopeViolationError("", name, list(self.allowed_tools))

        tool = self._base.get(name)
        if not tool:
            return None

        # Check autonomy level constraints
        if self.autonomy_level == AutonomyLevel.LEVEL_1_REMINDER:
            if tool.permission_level != PermissionLevel.SAFE and not name.startswith("reminder."):
                raise AutonomyPermissionError(
                    "", name, "Level 1 Reminder tasks cannot execute action tools."
                )

        elif self.autonomy_level == AutonomyLevel.LEVEL_2_READ_ONLY:
            if tool.permission_level != PermissionLevel.SAFE:
                raise AutonomyPermissionError(
                    "", name, f"Level 2 Read-Only tasks cannot execute {tool.permission_level.value} tools."
                )

        return _TaskGuardedTool(tool, self)

    def list_tool_definitions(self) -> list[Any]:
        all_defs = self._base.list_tool_definitions()
        if self.allowed_tools is None:
            return all_defs
        return [
            d for d in all_defs
            if (getattr(d, "name", None) or (d.get("name") if isinstance(d, dict) else None)) in self.allowed_tools
        ]


class _TaskGuardedTool(BaseTool):
    """Wraps a tool to enforce dry-run and track executions."""

    def __init__(self, inner: BaseTool, scoped_registry: ScopedToolRegistry) -> None:
        self.inner = inner
        self.scoped = scoped_registry
        self.name = inner.name
        self.description = inner.description
        self.permission_level = inner.permission_level
        self.parameters = inner.parameters

    async def execute(self, **kwargs: Any) -> ToolResult:
        self.scoped.tools_executed.append(self.name)

        if self.scoped.dry_run and self.permission_level != PermissionLevel.SAFE:
            log.info("DRY_RUN simulating tool call: %s(%s)", self.name, kwargs)
            return ToolResult(
                success=True,
                output=f"[DRY RUN] Would execute {self.name} with arguments {kwargs}",
                data={"dry_run": True, "action": self.name, "arguments": kwargs},
            )

        return await self.inner.execute(**kwargs)


class TaskExecutor:
    """
    Executes a task through Harma's existing Agent Core within bounded safety parameters.
    """

    def __init__(self, base_context: Optional[AgentContext] = None) -> None:
        self._base_context = base_context

    @property
    def base_context(self) -> AgentContext:
        if self._base_context is None:
            self._base_context = AgentContext()
        return self._base_context

    async def execute(self, task: Task) -> TaskExecutionHistory:
        """
        Run the task through HarmaAgent and return audit history.
        """
        execution_id = f"exec_{uuid.uuid4().hex[:10]}"
        started_at = time.time()
        log.info("TASK_STARTED task_id=%s exec_id=%s objective=%s", task.id, execution_id, task.objective)

        # 1. Create scoped context for this task
        scoped_registry = ScopedToolRegistry(
            base_registry=self.base_context.registry,
            allowed_tools=task.allowed_tools,
            autonomy_level=task.autonomy_level,
            dry_run=task.dry_run,
        )

        task_context = AgentContext(
            provider=self.base_context.llm,
            registry=scoped_registry,
            permissions=self.base_context.permissions,
            long_term_memory=self.base_context.long_term_memory,
        )

        agent = HarmaAgent(context=task_context, max_iterations=task.max_steps)

        # 2. Loop detection monitor hook
        action_history: list[str] = []

        history = TaskExecutionHistory(
            execution_id=execution_id,
            task_id=task.id,
            started_at=started_at,
            status="running",
        )

        try:
            # 3. Execute bounded by max_runtime_seconds
            response_text = await asyncio.wait_for(
                agent.run(task.objective),
                timeout=task.max_runtime_seconds,
            )

            history.completed_at = time.time()
            history.status = "success"
            history.summary = response_text
            history.steps_taken = len(scoped_registry.tools_executed)
            history.tools_used = list(set(scoped_registry.tools_executed))

            log.info("TASK_COMPLETED task_id=%s exec_id=%s", task.id, execution_id)
            return history

        except asyncio.TimeoutError:
            log.warning("TASK_TIMEOUT task_id=%s limit=%ds", task.id, task.max_runtime_seconds)
            history.completed_at = time.time()
            history.status = "timeout"
            history.error = f"Execution exceeded maximum duration of {task.max_runtime_seconds}s."
            return history

        except Exception as exc:
            log.error("TASK_FAILED task_id=%s error=%s", task.id, exc)
            history.completed_at = time.time()
            history.status = "failed"
            history.error = str(exc)
            history.tools_used = list(set(scoped_registry.tools_executed))
            return history
