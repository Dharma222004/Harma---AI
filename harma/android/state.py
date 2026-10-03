"""
Harma Android State Tracking

Tracks lightweight ephemeral state of Android sessions without duplicating
what can be observed directly from the device.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from harma.android.models import ScreenObservation


@dataclass
class AndroidState:
    """
    Ephemeral runtime state for the current session.
    Observation remains authoritative.
    """
    connected_device_id: Optional[str] = None
    current_package: str = ""
    current_activity: str = ""
    last_observation_time: float = 0.0
    last_action: str = ""
    action_count: int = 0
    recent_errors: list[str] = field(default_factory=list)

    def record_action(self, action: str, package: str = "") -> None:
        self.last_action = action
        self.action_count += 1
        if package:
            self.current_package = package

    def record_observation(self, obs: ScreenObservation) -> None:
        self.connected_device_id = obs.device_id
        self.current_package = obs.current_package
        self.current_activity = obs.current_activity
        self.last_observation_time = obs.timestamp

    def record_error(self, err: str) -> None:
        self.recent_errors.append(f"[{time.time()}] {err}")
        if len(self.recent_errors) > 10:
            self.recent_errors.pop(0)
