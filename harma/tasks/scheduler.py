"""
Harma Task Scheduler

Timezone-aware scheduler loop driving one-time, interval, recurring, and conditional tasks.
Accepts pluggable Clock for fast deterministic test execution without sleeping.
"""

from __future__ import annotations

import asyncio
from typing import Callable, Coroutine, Optional

from harma.config.logging_config import get_logger
from harma.tasks.conditions import ConditionWatcher
from harma.tasks.models import Task, TaskStatus, TriggerType
from harma.tasks.persistence import TaskStore
from harma.tasks.triggers import Clock, SystemClock, calculate_next_run

log = get_logger(__name__)


class TaskScheduler:
    """
    Evaluates task schedules, triggers due tasks, and recalculates recurring runs.
    """

    def __init__(
        self,
        store: TaskStore,
        clock: Optional[Clock] = None,
        poll_interval: float = 1.0,
    ) -> None:
        self.store = store
        self.clock: Clock = clock or SystemClock()
        self.poll_interval = poll_interval
        self.condition_watcher = ConditionWatcher()
        self._is_running = False
        self._task_runner: Optional[Callable[[Task], Coroutine]] = None
        self._loop_task: Optional[asyncio.Task] = None

    def set_task_runner(self, runner: Callable[[Task], Coroutine]) -> None:
        """Register the async function that executes a due task."""
        self._task_runner = runner

    def schedule(self, task: Task) -> Task:
        """Calculate next run time and mark task SCHEDULED."""
        now = self.clock.now()
        next_run = calculate_next_run(task.trigger, now, tz_name=task.timezone)
        task.next_run_at = next_run
        task.status = TaskStatus.SCHEDULED if next_run is not None else TaskStatus.EXPIRED
        self.store.save_task(task)
        log.info("TASK_SCHEDULED task_id=%s next_run=%s", task.id, task.next_run_at)
        return task

    async def get_due_tasks(self) -> list[Task]:
        """Find tasks whose next_run_at timestamp has passed."""
        now = self.clock.now()
        scheduled_tasks = self.store.list_tasks(status=TaskStatus.SCHEDULED)
        due: list[Task] = []

        for task in scheduled_tasks:
            # Conditional triggers evaluated via condition watcher
            if task.trigger.trigger_type == TriggerType.CONDITIONAL:
                if task.next_run_at is None or now >= task.next_run_at:
                    is_met = await self.condition_watcher.evaluate(task)
                    if is_met:
                        due.append(task)
                    else:
                        # Schedule next poll
                        task.next_run_at = now + task.trigger.condition_poll_interval
                        self.store.save_task(task)
            else:
                if task.next_run_at is not None and now >= task.next_run_at:
                    due.append(task)

        return due

    async def tick(self) -> list[Task]:
        """
        Execute a single evaluation cycle: find due tasks, dispatch them,
        and reschedule recurring tasks.
        """
        due_tasks = await self.get_due_tasks()
        dispatched: list[Task] = []

        for task in due_tasks:
            dispatched.append(task)
            # Reschedule if recurring or interval
            now = self.clock.now()
            if task.trigger.trigger_type in (TriggerType.RECURRING, TriggerType.INTERVAL):
                next_run = calculate_next_run(task.trigger, now, tz_name=task.timezone)
                task.next_run_at = next_run
                self.store.save_task(task)
            elif task.trigger.trigger_type == TriggerType.ONE_TIME:
                task.status = TaskStatus.COMPLETED
                self.store.save_task(task)

            # Trigger execution runner if attached
            if self._task_runner:
                asyncio.create_task(self._task_runner(task))

        return dispatched

    async def start(self) -> None:
        """Start background scheduler loop."""
        if self._is_running:
            return
        self._is_running = True
        self._loop_task = asyncio.create_task(self._run_loop())
        log.info("Task scheduler worker started.")

    async def stop(self) -> None:
        """Gracefully stop background scheduler loop."""
        self._is_running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        log.info("Task scheduler worker stopped.")

    async def _run_loop(self) -> None:
        while self._is_running:
            try:
                await self.tick()
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("Error in scheduler loop: %s", exc)
                await asyncio.sleep(1.0)
