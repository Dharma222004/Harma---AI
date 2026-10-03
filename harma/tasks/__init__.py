"""
Harma Proactive Tasks & Autonomous Execution (Phase 7)

Provides user-authorized, proactive background execution:
- Scheduled, recurring, interval, and conditional task triggers
- Timezone awareness and persistent storage
- Bounded autonomy levels, tool allowlists, and execution limits
- Action loop detection and emergency stop
- Integrated with Harma Agent Core, Tool Registry, Memory, and Voice
"""

from harma.tasks.exceptions import (
    AutonomyPermissionError,
    DuplicateTaskError,
    LoopDetectedError,
    ScopeViolationError,
    TaskConcurrencyLimitError,
    TaskError,
    TaskLockedError,
    TaskNotFoundError,
    TaskStepLimitError,
    TaskTimeoutError,
    TriggerValidationError,
)
from harma.tasks.executor import ScopedToolRegistry, TaskExecutor
from harma.tasks.locks import TaskLockManager
from harma.tasks.manager import (
    TaskManager,
    get_task_manager,
    reset_task_manager,
    set_task_manager,
)
from harma.tasks.models import (
    AutonomyLevel,
    Task,
    TaskExecutionHistory,
    TaskStatus,
    TaskTrigger,
    TriggerType,
)
from harma.tasks.notifications import NotificationManager
from harma.tasks.persistence import TaskStore
from harma.tasks.retry import ErrorCategory, ErrorClassifier, RetryPolicy
from harma.tasks.scheduler import TaskScheduler
from harma.tasks.tools import get_task_tools
from harma.tasks.triggers import (
    Clock,
    FakeClock,
    SystemClock,
    calculate_next_run,
    get_timezone,
    validate_trigger,
)

__all__ = [
    # Models & Enums
    "Task",
    "TaskStatus",
    "AutonomyLevel",
    "TaskTrigger",
    "TriggerType",
    "TaskExecutionHistory",
    # Exceptions
    "TaskError",
    "TaskNotFoundError",
    "TaskLockedError",
    "TaskConcurrencyLimitError",
    "TaskTimeoutError",
    "TaskStepLimitError",
    "LoopDetectedError",
    "ScopeViolationError",
    "AutonomyPermissionError",
    "DuplicateTaskError",
    "TriggerValidationError",
    # Clock & Triggers
    "Clock",
    "SystemClock",
    "FakeClock",
    "calculate_next_run",
    "validate_trigger",
    "get_timezone",
    # Storage & Locks
    "TaskStore",
    "TaskLockManager",
    "RetryPolicy",
    "ErrorClassifier",
    "ErrorCategory",
    "NotificationManager",
    # Execution & Scheduling
    "ScopedToolRegistry",
    "TaskExecutor",
    "TaskScheduler",
    "TaskManager",
    "get_task_manager",
    "set_task_manager",
    "reset_task_manager",
    "get_task_tools",
]
