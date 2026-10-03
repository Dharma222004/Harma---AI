"""
Harma Task Data Models

Defines structured representations for tasks, triggers, execution histories,
and autonomy profiles.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class TaskStatus(str, Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"              # Waiting for human confirmation / action
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class AutonomyLevel(str, Enum):
    LEVEL_0_MANUAL = "manual"                  # User triggers every step
    LEVEL_1_REMINDER = "reminder"              # Remind/notify user only
    LEVEL_2_READ_ONLY = "read_only"            # Auto-execute SAFE/read-only tools
    LEVEL_3_LOW_RISK = "low_risk"              # Auto-execute SAFE + low-risk actions
    LEVEL_4_CONSEQUENTIAL = "consequential"    # Pre-authorized actions; prompts if unexpected


class TriggerType(str, Enum):
    ONE_TIME = "one_time"
    RECURRING = "recurring"
    INTERVAL = "interval"
    CONDITIONAL = "conditional"


@dataclass
class TaskTrigger:
    """Specification of how and when a task is triggered."""

    trigger_type: TriggerType = TriggerType.ONE_TIME
    run_at: Optional[float] = None              # Unix epoch timestamp for one-time
    daily_time: Optional[str] = None            # "HH:MM", e.g. "09:00"
    weekly_days: list[int] = field(default_factory=list)  # 0=Monday .. 6=Sunday
    interval_seconds: Optional[float] = None    # e.g. 7200 for every 2 hours
    condition_query: Optional[str] = None       # e.g. "price_changed" or URL
    condition_poll_interval: float = 300.0      # Minimum polling interval in seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger_type": self.trigger_type.value,
            "run_at": self.run_at,
            "daily_time": self.daily_time,
            "weekly_days": self.weekly_days,
            "interval_seconds": self.interval_seconds,
            "condition_query": self.condition_query,
            "condition_poll_interval": self.condition_poll_interval,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskTrigger":
        tt_str = data.get("trigger_type", TriggerType.ONE_TIME.value)
        tt = TriggerType(tt_str) if isinstance(tt_str, str) else TriggerType.ONE_TIME
        return cls(
            trigger_type=tt,
            run_at=data.get("run_at"),
            daily_time=data.get("daily_time"),
            weekly_days=data.get("weekly_days", []),
            interval_seconds=data.get("interval_seconds"),
            condition_query=data.get("condition_query"),
            condition_poll_interval=data.get("condition_poll_interval", 300.0),
        )


@dataclass
class TaskExecutionHistory:
    """Persistent audit record of a single task execution."""

    execution_id: str
    task_id: str
    started_at: float
    completed_at: Optional[float] = None
    status: str = "running"
    summary: str = ""
    error: Optional[str] = None
    steps_taken: int = 0
    tools_used: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "summary": self.summary,
            "error": self.error,
            "steps_taken": self.steps_taken,
            "tools_used": self.tools_used,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskExecutionHistory":
        return cls(
            execution_id=data["execution_id"],
            task_id=data["task_id"],
            started_at=data["started_at"],
            completed_at=data.get("completed_at"),
            status=data.get("status", "running"),
            summary=data.get("summary", ""),
            error=data.get("error"),
            steps_taken=data.get("steps_taken", 0),
            tools_used=data.get("tools_used", []),
        )


@dataclass
class Task:
    """Core Task entity for proactive and autonomous background execution."""

    id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:10]}")
    name: str = "Untitled Task"
    objective: str = ""
    status: TaskStatus = TaskStatus.SCHEDULED
    trigger: TaskTrigger = field(default_factory=TaskTrigger)
    autonomy_level: AutonomyLevel = AutonomyLevel.LEVEL_2_READ_ONLY
    allowed_tools: list[str] = field(default_factory=list)
    timezone: str = "UTC"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    next_run_at: Optional[float] = None
    last_run_at: Optional[float] = None
    execution_count: int = 0
    max_runtime_seconds: float = 300.0
    max_steps: int = 50
    max_retries: int = 3
    retry_count: int = 0
    last_error: Optional[str] = None
    notification_channels: list[str] = field(default_factory=lambda: ["cli"])
    dry_run: bool = False
    idempotency_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.trigger.trigger_type == TriggerType.ONE_TIME:
            if self.trigger.run_at is None and self.next_run_at is not None:
                self.trigger.run_at = self.next_run_at
            elif self.trigger.run_at is not None and self.next_run_at is None:
                self.next_run_at = self.trigger.run_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "objective": self.objective,
            "status": self.status.value,
            "trigger": self.trigger.to_dict(),
            "autonomy_level": self.autonomy_level.value,
            "allowed_tools": self.allowed_tools,
            "timezone": self.timezone,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "next_run_at": self.next_run_at,
            "last_run_at": self.last_run_at,
            "execution_count": self.execution_count,
            "max_runtime_seconds": self.max_runtime_seconds,
            "max_steps": self.max_steps,
            "max_retries": self.max_retries,
            "retry_count": self.retry_count,
            "last_error": self.last_error,
            "notification_channels": self.notification_channels,
            "dry_run": self.dry_run,
            "idempotency_key": self.idempotency_key,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        return cls(
            id=data["id"],
            name=data.get("name", "Untitled Task"),
            objective=data.get("objective", ""),
            status=TaskStatus(data.get("status", TaskStatus.SCHEDULED.value)),
            trigger=TaskTrigger.from_dict(data.get("trigger", {})),
            autonomy_level=AutonomyLevel(data.get("autonomy_level", AutonomyLevel.LEVEL_2_READ_ONLY.value)),
            allowed_tools=data.get("allowed_tools", []),
            timezone=data.get("timezone", "UTC"),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            next_run_at=data.get("next_run_at"),
            last_run_at=data.get("last_run_at"),
            execution_count=data.get("execution_count", 0),
            max_runtime_seconds=data.get("max_runtime_seconds", 300.0),
            max_steps=data.get("max_steps", 50),
            max_retries=data.get("max_retries", 3),
            retry_count=data.get("retry_count", 0),
            last_error=data.get("last_error"),
            notification_channels=data.get("notification_channels", ["cli"]),
            dry_run=bool(data.get("dry_run", False)),
            idempotency_key=data.get("idempotency_key", ""),
            metadata=data.get("metadata", {}),
        )
