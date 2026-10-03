"""
Harma Tasks Exceptions

Defines the error hierarchy for the proactive task and autonomous execution subsystem.
"""

from __future__ import annotations


class TaskError(Exception):
    """Base exception for all task system errors."""

    def __init__(self, message: str, code: str = "TASK_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class TaskNotFoundError(TaskError):
    """Raised when a task with the given ID cannot be found."""

    def __init__(self, task_id: str) -> None:
        super().__init__(f"Task '{task_id}' not found.", code="TASK_NOT_FOUND")
        self.task_id = task_id


class TaskLockedError(TaskError):
    """Raised when an execution is attempted on an already running task."""

    def __init__(self, task_id: str) -> None:
        super().__init__(
            f"Task '{task_id}' is already running. Concurrent execution blocked.",
            code="TASK_LOCKED",
        )
        self.task_id = task_id


class TaskConcurrencyLimitError(TaskError):
    """Raised when max concurrent task limit is reached."""

    def __init__(self, limit: int) -> None:
        super().__init__(
            f"Maximum concurrent task limit ({limit}) reached. Task queued.",
            code="CONCURRENCY_LIMIT_REACHED",
        )
        self.limit = limit


class TaskTimeoutError(TaskError):
    """Raised when a task exceeds its maximum allowed execution runtime."""

    def __init__(self, task_id: str, timeout: float) -> None:
        super().__init__(
            f"Task '{task_id}' exceeded runtime limit of {timeout}s.",
            code="TASK_TIMEOUT",
        )
        self.task_id = task_id
        self.timeout = timeout


class TaskStepLimitError(TaskError):
    """Raised when a task exceeds its maximum allowed tool execution steps."""

    def __init__(self, task_id: str, max_steps: int) -> None:
        super().__init__(
            f"Task '{task_id}' exceeded max step limit of {max_steps} steps.",
            code="TASK_STEP_LIMIT_EXCEEDED",
        )
        self.task_id = task_id
        self.max_steps = max_steps


class LoopDetectedError(TaskError):
    """Raised when repeated identical actions without state change are detected."""

    def __init__(self, task_id: str, action: str) -> None:
        super().__init__(
            f"Task '{task_id}' halted: loop detected on action '{action}'.",
            code="LOOP_DETECTED",
        )
        self.task_id = task_id
        self.action = action


class ScopeViolationError(TaskError):
    """Raised when an autonomous task attempts to execute a tool outside its allowed scope."""

    def __init__(self, task_id: str, tool_name: str, allowed_tools: list[str]) -> None:
        super().__init__(
            f"Task '{task_id}' attempted to use unauthorized tool '{tool_name}'. "
            f"Allowed tools: {allowed_tools}",
            code="SCOPE_VIOLATION",
        )
        self.task_id = task_id
        self.tool_name = tool_name
        self.allowed_tools = allowed_tools


class AutonomyPermissionError(TaskError):
    """Raised when an autonomous task requires higher autonomy level or user confirmation."""

    def __init__(self, task_id: str, action: str, reason: str) -> None:
        super().__init__(
            f"Task '{task_id}' blocked on action '{action}': {reason}",
            code="AUTONOMY_PERMISSION_BLOCKED",
        )
        self.task_id = task_id
        self.action = action
        self.reason = reason


class DuplicateTaskError(TaskError):
    """Raised when an identical scheduled task already exists."""

    def __init__(self, objective: str, existing_id: str) -> None:
        super().__init__(
            f"A similar task with objective '{objective}' already exists (ID: {existing_id}).",
            code="DUPLICATE_TASK",
        )
        self.objective = objective
        self.existing_id = existing_id


class TriggerValidationError(TaskError):
    """Raised when trigger specification is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="INVALID_TRIGGER")
