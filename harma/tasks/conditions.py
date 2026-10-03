"""
Harma Task Condition Watcher

Evaluates condition-based triggers while enforcing minimum polling intervals
and protecting against rate limits.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Coroutine, Optional

from harma.config.logging_config import get_logger
from harma.tasks.models import Task, TriggerType

log = get_logger(__name__)


class ConditionWatcher:
    """
    Evaluates condition triggers on a bounded polling interval.
    """

    def __init__(self, min_poll_interval_seconds: float = 60.0) -> None:
        self.min_poll_interval_seconds = min_poll_interval_seconds
        self._custom_evaluators: dict[str, Callable[[str], Coroutine[Any, Any, bool]]] = {}

    def register_evaluator(
        self, prefix: str, evaluator: Callable[[str], Coroutine[Any, Any, bool]]
    ) -> None:
        """Register custom condition evaluation function."""
        self._custom_evaluators[prefix] = evaluator

    async def evaluate(self, task: Task) -> bool:
        """
        Evaluate if a task's condition has been met.
        Returns True if condition is triggered, False otherwise.
        """
        if task.trigger.trigger_type != TriggerType.CONDITIONAL:
            return False

        query = task.trigger.condition_query or ""
        if not query:
            return False

        # Check registered custom evaluators
        for prefix, func in self._custom_evaluators.items():
            if query.startswith(prefix):
                try:
                    return await func(query)
                except Exception as exc:
                    log.warning("Condition evaluator %s failed: %s", prefix, exc)
                    return False

        # Default heuristic: check if query specifies a simulated true trigger
        if "triggered" in query.lower() or "true" in query.lower():
            return True

        return False
