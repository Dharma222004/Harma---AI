"""
Harma Task Locking & Concurrency Control

Prevents duplicate concurrent executions of the same task and enforces
global concurrent task limits.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from harma.tasks.exceptions import TaskConcurrencyLimitError, TaskLockedError


class TaskLockManager:
    """
    Manages per-task locks and global concurrency semaphore.
    """

    def __init__(self, max_concurrent_tasks: int = 3) -> None:
        self.max_concurrent_tasks = max_concurrent_tasks
        self._running_tasks: set[str] = set()
        self._semaphore = asyncio.Semaphore(max_concurrent_tasks)
        self._mutex = asyncio.Lock()

    async def is_locked(self, task_id: str) -> bool:
        async with self._mutex:
            return task_id in self._running_tasks

    async def running_count(self) -> int:
        async with self._mutex:
            return len(self._running_tasks)

    @asynccontextmanager
    async def task_execution_guard(self, task_id: str) -> AsyncGenerator[None, None]:
        """
        Async context manager that acquires both the per-task lock and a concurrency slot.
        Raises:
            TaskLockedError: If this specific task is already running.
            TaskConcurrencyLimitError: If max concurrent tasks are active.
        """
        async with self._mutex:
            if task_id in self._running_tasks:
                raise TaskLockedError(task_id)

            if len(self._running_tasks) >= self.max_concurrent_tasks:
                raise TaskConcurrencyLimitError(self.max_concurrent_tasks)

            self._running_tasks.add(task_id)

        try:
            yield
        finally:
            async with self._mutex:
                self._running_tasks.discard(task_id)
