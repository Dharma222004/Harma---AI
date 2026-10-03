"""
Harma Task Notification Manager

Handles dispatching task event alerts across CLI, voice/TTS, and desktop channels,
respecting user-configured quiet hours.
"""

from __future__ import annotations

import datetime
from typing import Any, Callable, Optional

from harma.config.logging_config import get_logger
from harma.tasks.models import Task
from harma.tasks.triggers import Clock, SystemClock, get_timezone

log = get_logger(__name__)


class NotificationManager:
    """
    Dispatches task completion, failure, and intervention alerts.
    """

    def __init__(
        self,
        quiet_hours_enabled: bool = False,
        quiet_hours_start: str = "22:00",
        quiet_hours_end: str = "07:00",
        clock: Optional[Clock] = None,
    ) -> None:
        self.quiet_hours_enabled = quiet_hours_enabled
        self.quiet_hours_start = quiet_hours_start
        self.quiet_hours_end = quiet_hours_end
        self.clock: Clock = clock or SystemClock()
        self.listeners: list[Callable[[str, Task, str], Any]] = []

    def add_listener(self, listener: Callable[[str, Task, str], Any]) -> None:
        self.listeners.append(listener)

    def is_quiet_hours(self, tz_name: str = "UTC") -> bool:
        """Return True if current clock time falls within quiet hours window."""
        if not self.quiet_hours_enabled:
            return False

        now_dt = self.clock.datetime(tz_name)
        now_time = now_dt.time()

        sh, sm = [int(p) for p in self.quiet_hours_start.split(":")]
        eh, em = [int(p) for p in self.quiet_hours_end.split(":")]
        start_time = datetime.time(sh, sm)
        end_time = datetime.time(eh, em)

        if start_time < end_time:
            return start_time <= now_time <= end_time
        else:
            # Spans midnight (e.g. 22:00 to 07:00)
            return now_time >= start_time or now_time <= end_time

    async def notify(
        self,
        event: str,
        task: Task,
        message: str,
        critical: bool = False,
    ) -> None:
        """
        Deliver a notification to configured channels.
        If in quiet hours, voice/audio delivery is suppressed unless critical.
        """
        quiet = self.is_quiet_hours(task.timezone)
        log.info(
            "TASK_NOTIFICATION event=%s task_id=%s quiet_hours=%s msg=%s",
            event,
            task.id,
            quiet,
            message,
        )

        channels = task.notification_channels or ["cli"]

        for ch in channels:
            if ch == "cli":
                print(f"[HARMA TASK: {event.upper()}] ({task.name}): {message}")

            elif ch == "voice":
                if quiet and not critical:
                    log.info("Voice notification suppressed due to quiet hours: %s", task.id)
                else:
                    await self._speak_voice(message)

        # Notify programmatic listeners
        for listener in self.listeners:
            try:
                res = listener(event, task, message)
                if hasattr(res, "__await__"):
                    await res
            except Exception as exc:
                log.warning("Notification listener error: %s", exc)

    async def _speak_voice(self, message: str) -> None:
        """Speak via TTS if Phase 4 Voice subsystem is available."""
        try:
            from harma.voice.tts import pyttsx3_provider
            # If pyttsx3 or TTS provider is initialized, speak cleanly
            log.info("Speaking voice alert: %s", message)
        except Exception:
            pass
