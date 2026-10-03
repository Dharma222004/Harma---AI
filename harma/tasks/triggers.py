"""
Harma Task Triggers & Time Calculations

Timezone-aware scheduling engine with pluggable clock abstraction for deterministic testing.
"""

from __future__ import annotations

import datetime
import time
from abc import ABC, abstractmethod
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from harma.tasks.exceptions import TriggerValidationError
from harma.tasks.models import TaskTrigger, TriggerType


class Clock(ABC):
    """Abstract clock interface allowing controllable time in tests."""

    @abstractmethod
    def now(self) -> float:
        """Current epoch timestamp in seconds."""

    @abstractmethod
    def datetime(self, tz_name: str = "UTC") -> datetime.datetime:
        """Current timezone-aware datetime."""


class SystemClock(Clock):
    """Production clock using real system wall time."""

    def now(self) -> float:
        return time.time()

    def datetime(self, tz_name: str = "UTC") -> datetime.datetime:
        tz = get_timezone(tz_name)
        return datetime.datetime.now(tz)


class FakeClock(Clock):
    """Controllable clock for fast deterministic testing without real sleep."""

    def __init__(self, initial_time: Optional[float] = None) -> None:
        self._current_time: float = initial_time or 1700000000.0  # arbitrary baseline

    def now(self) -> float:
        return self._current_time

    def set_time(self, timestamp: float) -> None:
        self._current_time = timestamp

    def advance(self, seconds: float) -> None:
        self._current_time += seconds

    def datetime(self, tz_name: str = "UTC") -> datetime.datetime:
        tz = get_timezone(tz_name)
        return datetime.datetime.fromtimestamp(self._current_time, tz=tz)


def get_timezone(tz_name: str) -> datetime.tzinfo:
    """Resolve timezone string to tzinfo object, falling back safely to UTC."""
    if not tz_name or tz_name.lower() in ("utc", "z"):
        return datetime.timezone.utc
    if tz_name.lower() == "local":
        return datetime.datetime.now().astimezone().tzinfo or datetime.timezone.utc
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        return datetime.timezone.utc


def validate_trigger(trigger: TaskTrigger) -> None:
    """Validate trigger fields."""
    if trigger.trigger_type == TriggerType.ONE_TIME:
        if trigger.run_at is None:
            raise TriggerValidationError("One-time trigger requires 'run_at' timestamp.")

    elif trigger.trigger_type == TriggerType.INTERVAL:
        if not trigger.interval_seconds or trigger.interval_seconds <= 0:
            raise TriggerValidationError("Interval trigger requires 'interval_seconds' > 0.")

    elif trigger.trigger_type == TriggerType.RECURRING:
        if not trigger.daily_time:
            raise TriggerValidationError("Recurring trigger requires 'daily_time' in HH:MM format.")
        try:
            parts = trigger.daily_time.split(":")
            if len(parts) != 2:
                raise ValueError()
            h, m = int(parts[0]), int(parts[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError()
        except ValueError:
            raise TriggerValidationError(f"Invalid daily_time format '{trigger.daily_time}'. Expected 'HH:MM'.")

        for d in trigger.weekly_days:
            if not (0 <= d <= 6):
                raise TriggerValidationError(f"Invalid weekly day {d}. Expected 0 (Mon) to 6 (Sun).")

    elif trigger.trigger_type == TriggerType.CONDITIONAL:
        if not trigger.condition_query:
            raise TriggerValidationError("Conditional trigger requires 'condition_query'.")
        if trigger.condition_poll_interval < 1.0:
            raise TriggerValidationError("Condition poll interval must be at least 1.0 second.")


def calculate_next_run(
    trigger: TaskTrigger,
    current_time: float,
    tz_name: str = "UTC",
) -> Optional[float]:
    """
    Compute next execution epoch timestamp for a trigger.
    Returns None if trigger has expired (e.g. past one-time run).
    """
    validate_trigger(trigger)

    if trigger.trigger_type == TriggerType.ONE_TIME:
        if trigger.run_at and trigger.run_at > current_time:
            return trigger.run_at
        return None

    elif trigger.trigger_type == TriggerType.INTERVAL:
        interval = trigger.interval_seconds or 3600.0
        return current_time + interval

    elif trigger.trigger_type == TriggerType.CONDITIONAL:
        # Next poll time
        return current_time + trigger.condition_poll_interval

    elif trigger.trigger_type == TriggerType.RECURRING:
        tz = get_timezone(tz_name)
        now_dt = datetime.datetime.fromtimestamp(current_time, tz=tz)

        # Parse target hour and minute
        parts = (trigger.daily_time or "09:00").split(":")
        target_h, target_m = int(parts[0]), int(parts[1])

        # Candidate for today
        candidate = now_dt.replace(hour=target_h, minute=target_m, second=0, microsecond=0)

        days_filter = set(trigger.weekly_days) if trigger.weekly_days else set(range(7))

        # Check candidate today or advance day by day until matching weekday and in the future
        for day_offset in range(15):  # search up to 2 weeks
            check_dt = candidate + datetime.timedelta(days=day_offset)
            if check_dt.weekday() in days_filter and check_dt.timestamp() > current_time:
                return check_dt.timestamp()

        # Fallback 1 day ahead
        return (candidate + datetime.timedelta(days=1)).timestamp()

    return None
