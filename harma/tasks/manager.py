"""
Harma Task Manager

Top-level orchestrator for proactive autonomous tasks.
Integrates store, scheduler, executor, locks, retry policy, and notification manager.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from harma.config.logging_config import get_logger
from harma.tasks.exceptions import (
    DuplicateTaskError,
    TaskLockedError,
    TaskNotFoundError,
)
from harma.tasks.executor import TaskExecutor
from harma.tasks.locks import TaskLockManager
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
from harma.tasks.triggers import Clock, SystemClock

log = get_logger(__name__)


class TaskManager:
    """
    Central API for task lifecycle, scheduling, execution, and emergency controls.
    """

    def __init__(
        self,
        store: Optional[TaskStore] = None,
        clock: Optional[Clock] = None,
        executor: Optional[TaskExecutor] = None,
        max_concurrent_tasks: int = 3,
        auto_start_scheduler: bool = False,
    ) -> None:
        global _global_task_manager
        if _global_task_manager is None:
            _global_task_manager = self

        self.clock: Clock = clock or SystemClock()
        self.store = store or TaskStore()
        self.scheduler = TaskScheduler(store=self.store, clock=self.clock)
        self.executor = executor or TaskExecutor()
        self.lock_manager = TaskLockManager(max_concurrent_tasks=max_concurrent_tasks)
        self.retry_policy = RetryPolicy(max_attempts=3)
        self.notification_manager = NotificationManager(clock=self.clock)

        # Wire scheduler to execute tasks
        self.scheduler.set_task_runner(self._run_scheduled_task)

        # Restore persisted tasks into scheduler
        self.restore()

        if auto_start_scheduler:
            asyncio.create_task(self.scheduler.start())

    def restore(self) -> None:
        """Reload all persisted tasks and re-register scheduled ones."""
        active_tasks = self.store.list_tasks(status=TaskStatus.SCHEDULED)
        for task in active_tasks:
            try:
                self.scheduler.schedule(task)
            except Exception as e:
                log.warning("Could not restore task %s: %s", task.id, e)
        log.info("Task manager restored %d active tasks.", len(active_tasks))

    async def create_task(
        self,
        name: str,
        objective: str,
        trigger: TaskTrigger,
        autonomy_level: AutonomyLevel = AutonomyLevel.LEVEL_2_READ_ONLY,
        allowed_tools: Optional[list[str]] = None,
        timezone: str = "UTC",
        max_runtime_seconds: float = 300.0,
        max_steps: int = 50,
        max_retries: int = 3,
        notification_channels: Optional[list[str]] = None,
        dry_run: bool = False,
        idempotency_key: str = "",
        check_duplicate: bool = True,
    ) -> Task:
        """Create, validate, persist, and schedule a new task."""
        # Duplicate detection check
        if check_duplicate:
            existing = self.store.list_tasks()
            for t in existing:
                if (
                    t.status in (TaskStatus.SCHEDULED, TaskStatus.RUNNING)
                    and t.objective.strip().lower() == objective.strip().lower()
                    and t.trigger.trigger_type == trigger.trigger_type
                ):
                    raise DuplicateTaskError(objective, t.id)

        task = Task(
            name=name,
            objective=objective,
            status=TaskStatus.SCHEDULED,
            trigger=trigger,
            autonomy_level=autonomy_level,
            allowed_tools=allowed_tools or [],
            timezone=timezone,
            created_at=self.clock.now(),
            updated_at=self.clock.now(),
            max_runtime_seconds=max_runtime_seconds,
            max_steps=max_steps,
            max_retries=max_retries,
            notification_channels=notification_channels or ["cli"],
            dry_run=dry_run,
            idempotency_key=idempotency_key,
        )

        # Calculate next run and schedule
        self.scheduler.schedule(task)
        log.info("TASK_CREATED task_id=%s name=%r objective=%r", task.id, task.name, task.objective)
        return task

    def get_task(self, task_id: str) -> Task:
        task = self.store.get_task(task_id)
        if not task:
            raise TaskNotFoundError(task_id)
        return task

    def list_tasks(self, status: Optional[TaskStatus] = None) -> list[Task]:
        return self.store.list_tasks(status=status)

    def update_task(self, task_id: str, **kwargs: Any) -> Task:
        task = self.get_task(task_id)
        for k, v in kwargs.items():
            if hasattr(task, k):
                setattr(task, k, v)
        task.updated_at = self.clock.now()

        if "trigger" in kwargs or "timezone" in kwargs:
            self.scheduler.schedule(task)
        else:
            self.store.save_task(task)

        return task

    def pause_task(self, task_id: str) -> Task:
        task = self.get_task(task_id)
        task.status = TaskStatus.PAUSED
        task.updated_at = self.clock.now()
        self.store.save_task(task)
        log.info("TASK_PAUSED task_id=%s", task_id)
        return task

    def resume_task(self, task_id: str) -> Task:
        task = self.get_task(task_id)
        if task.status == TaskStatus.PAUSED:
            self.scheduler.schedule(task)
            log.info("TASK_RESUMED task_id=%s", task_id)
        return task

    def cancel_task(self, task_id: str) -> Task:
        task = self.get_task(task_id)
        task.status = TaskStatus.CANCELLED
        task.next_run_at = None
        task.updated_at = self.clock.now()
        self.store.save_task(task)
        log.info("TASK_CANCELLED task_id=%s", task_id)
        return task

    def delete_task(self, task_id: str) -> bool:
        deleted = self.store.delete_task(task_id)
        log.info("TASK_DELETED task_id=%s success=%s", task_id, deleted)
        return deleted

    async def run_task_now(self, task_id: str) -> TaskExecutionHistory:
        """Trigger an immediate execution of a task."""
        task = self.get_task(task_id)
        return await self._execute_with_guards(task)

    async def _run_scheduled_task(self, task: Task) -> None:
        """Invoked by the scheduler loop when a task is due."""
        try:
            await self._execute_with_guards(task)
        except Exception as exc:
            log.error("Unhandled error running scheduled task %s: %s", task.id, exc)

    async def _execute_with_guards(self, task: Task) -> TaskExecutionHistory:
        """
        Execute task protected by per-task lock, concurrency limits, and retry policy.
        """
        async with self.lock_manager.task_execution_guard(task.id):
            task.status = TaskStatus.RUNNING
            task.last_run_at = self.clock.now()
            task.execution_count += 1
            self.store.save_task(task)

            history = await self.executor.execute(task)
            self.store.save_execution(history)

            if history.status == "success":
                task.status = (
                    TaskStatus.SCHEDULED
                    if task.trigger.trigger_type != TriggerType.ONE_TIME
                    else TaskStatus.COMPLETED
                )
                task.retry_count = 0
                task.last_error = None
                self.store.save_task(task)
                await self.notification_manager.notify(
                    event="completed",
                    task=task,
                    message=f"Task completed successfully: {history.summary[:120]}",
                )

            elif history.status in ("failed", "timeout"):
                category = ErrorClassifier.classify(history.error or "")
                if category == ErrorCategory.USER_ACTION_REQUIRED:
                    task.status = TaskStatus.WAITING
                    self.store.save_task(task)
                    await self.notification_manager.notify(
                        event="user_action_required",
                        task=task,
                        message=f"Task paused: {history.error}",
                        critical=True,
                    )
                elif self.retry_policy.should_retry(task.retry_count, history.error or ""):
                    task.retry_count += 1
                    task.status = TaskStatus.SCHEDULED
                    task.last_error = history.error
                    backoff = self.retry_policy.compute_backoff(task.retry_count)
                    task.next_run_at = self.clock.now() + backoff
                    self.store.save_task(task)
                    log.info("TASK_RETRY task_id=%s attempt=%d backoff=%.1fs", task.id, task.retry_count, backoff)
                else:
                    task.status = TaskStatus.FAILED
                    task.last_error = history.error
                    self.store.save_task(task)
                    await self.notification_manager.notify(
                        event="failed",
                        task=task,
                        message=f"Task failed: {history.error}",
                    )

            return history

    def get_history(
        self, task_id: Optional[str] = None, limit: int = 50
    ) -> list[TaskExecutionHistory]:
        return self.store.list_executions(task_id=task_id, limit=limit)

    async def stop_all(self) -> int:
        """Emergency Stop: pause all active and scheduled tasks immediately."""
        active = self.store.list_tasks(status=TaskStatus.SCHEDULED)
        for t in active:
            self.pause_task(t.id)
        log.warning("EMERGENCY_STOP paused %d scheduled tasks.", len(active))
        return len(active)

    def stats(self) -> dict[str, Any]:
        """Dashboard statistics on tasks."""
        all_tasks = self.store.list_tasks()
        counts: dict[str, int] = {}
        for t in all_tasks:
            counts[t.status.value] = counts.get(t.status.value, 0) + 1

        scheduled = [t for t in all_tasks if t.status == TaskStatus.SCHEDULED and t.next_run_at]
        next_run = min((t.next_run_at for t in scheduled), default=None)

        return {
            "total": len(all_tasks),
            "by_status": counts,
            "next_execution": next_run,
        }


# Singleton accessor
_global_task_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    global _global_task_manager
    if _global_task_manager is None:
        _global_task_manager = TaskManager()
    return _global_task_manager


def set_task_manager(manager: TaskManager) -> None:
    global _global_task_manager
    _global_task_manager = manager


def reset_task_manager() -> None:
    global _global_task_manager
    _global_task_manager = None
