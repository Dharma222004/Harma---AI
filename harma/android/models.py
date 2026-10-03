"""
Harma Android Data Models

Defines structured representations for Android devices, screens, UI elements,
apps, notifications, and action results.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class DeviceConnectionState(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    UNAUTHORIZED = "unauthorized"
    RECOVERY = "recovery"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


@dataclass
class Point:
    """2D screen coordinate point."""
    x: int
    y: int

    def to_tuple(self) -> tuple[int, int]:
        return (self.x, self.y)


@dataclass
class Bounds:
    """Bounding box coordinates [left, top][right, bottom]."""
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def center(self) -> Point:
        return Point(
            x=self.left + self.width // 2,
            y=self.top + self.height // 2,
        )

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x <= self.right and self.top <= y <= self.bottom

    @classmethod
    def from_str(cls, bounds_str: str) -> "Bounds":
        """
        Parse Android uiautomator bounds format: '[left,top][right,bottom]'.
        Example: '[0,0][1080,2400]'
        """
        match = re.findall(r"\[(\d+),(\d+)\]", bounds_str)
        if len(match) >= 2:
            left, top = int(match[0][0]), int(match[0][1])
            right, bottom = int(match[1][0]), int(match[1][1])
            return cls(left=left, top=top, right=right, bottom=bottom)
        return cls(left=0, top=0, right=0, bottom=0)

    def to_dict(self) -> dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
            "width": self.width,
            "height": self.height,
            "center_x": self.center.x,
            "center_y": self.center.y,
        }


@dataclass
class UIElement:
    """
    Normalized representation of an Android accessibility / UI hierarchy node.
    """
    id: str = ""                         # resource-id
    role: str = ""                       # class / widget type (e.g. android.widget.Button)
    text: str = ""                       # visible text
    content_description: str = ""        # accessibility description
    bounds: Bounds = field(default_factory=lambda: Bounds(0, 0, 0, 0))
    clickable: bool = False
    enabled: bool = True
    checked: bool = False
    checkable: bool = False
    focused: bool = False
    selected: bool = False
    scrollable: bool = False
    long_clickable: bool = False
    password: bool = False               # True if password field
    package: str = ""
    parent_id: Optional[str] = None
    children: list["UIElement"] = field(default_factory=list)

    @property
    def center(self) -> tuple[int, int]:
        p = self.bounds.center
        return (p.x, p.y)

    @property
    def simple_role(self) -> str:
        """Return simplified role name, e.g. 'Button' instead of 'android.widget.Button'."""
        if not self.role:
            return "Element"
        return self.role.split(".")[-1]

    def matches(self, query: str) -> bool:
        """
        Check if element matches search query against text, description, id, or role.
        """
        q = query.strip().lower()
        if not q:
            return False

        # 1. Exact or case-insensitive match on text
        if self.text and q == self.text.lower():
            return True

        # 2. Match on content description
        if self.content_description and q == self.content_description.lower():
            return True

        # 3. Match on resource id (full or suffix)
        if self.id:
            id_lower = self.id.lower()
            if q == id_lower or id_lower.endswith(f"/{q}") or id_lower.endswith(f":id/{q}"):
                return True

        # 4. Substring in text or content description
        if self.text and q in self.text.lower():
            return True
        if self.content_description and q in self.content_description.lower():
            return True

        # 5. Role match
        if self.simple_role.lower() == q:
            return True

        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.simple_role,
            "text": self.text,
            "content_description": self.content_description,
            "bounds": self.bounds.to_dict(),
            "center": self.center,
            "clickable": self.clickable,
            "enabled": self.enabled,
            "checked": self.checked,
            "focused": self.focused,
            "package": self.package,
        }


@dataclass
class ScreenObservation:
    """
    Structured observation of the Android device screen.
    """
    device_id: str
    timestamp: float = field(default_factory=time.time)
    width: int = 1080
    height: int = 2400
    current_package: str = ""
    current_activity: str = ""
    elements: list[UIElement] = field(default_factory=list)
    screenshot_path: Optional[str] = None
    screenshot_bytes: Optional[bytes] = None
    is_locked: bool = False
    summary: str = ""

    def find_element(self, query: str) -> Optional[UIElement]:
        """
        Find first matching UI element following the priority resolution order:
          1. Resource ID
          2. Content description exact match
          3. Text exact match
          4. Text / description substring
          5. Role match
        """
        q = query.strip().lower()
        if not q:
            return None

        # Priority 1: Resource ID
        for el in self.elements:
            if el.id:
                id_lower = el.id.lower()
                if q == id_lower or id_lower.endswith(f"/{q}") or id_lower.endswith(f":id/{q}"):
                    return el

        # Priority 2: Content description exact match
        for el in self.elements:
            if el.content_description and el.content_description.lower() == q:
                return el

        # Priority 3: Visible text exact match
        for el in self.elements:
            if el.text and el.text.lower() == q:
                return el

        # Priority 4: Substring match (text or content description)
        for el in self.elements:
            if (el.text and q in el.text.lower()) or (
                el.content_description and q in el.content_description.lower()
            ):
                return el

        # Priority 5: Role match
        for el in self.elements:
            if el.simple_role.lower() == q:
                return el

        return None

    def find_all_elements(self, query: str) -> list[UIElement]:
        """Find all matching UI elements."""
        return [el for el in self.elements if el.matches(query)]

    def interactive_elements(self) -> list[UIElement]:
        """Return list of clickable, checkable, or scrollable elements."""
        return [el for el in self.elements if el.clickable or el.checkable or el.scrollable]

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "timestamp": self.timestamp,
            "dimensions": f"{self.width}x{self.height}",
            "current_package": self.current_package,
            "current_activity": self.current_activity,
            "is_locked": self.is_locked,
            "elements_count": len(self.elements),
            "summary": self.summary,
            "interactive_elements": [
                el.to_dict() for el in self.interactive_elements()[:15]
            ],
        }


@dataclass
class AndroidDevice:
    """Android device connection abstraction."""
    device_id: str
    model: str = "Unknown"
    manufacturer: str = "Unknown"
    android_version: str = "Unknown"
    screen_width: int = 1080
    screen_height: int = 2400
    state: DeviceConnectionState = DeviceConnectionState.CONNECTED
    is_emulator: bool = False
    is_locked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "model": self.model,
            "manufacturer": self.manufacturer,
            "android_version": self.android_version,
            "screen_size": f"{self.screen_width}x{self.screen_height}",
            "state": self.state.value,
            "is_emulator": self.is_emulator,
            "is_locked": self.is_locked,
        }


@dataclass
class DeviceStatus:
    """Detailed operational status of an Android device."""
    device_id: str
    manufacturer: str = "Unknown"
    model: str = "Unknown"
    android_version: str = "Unknown"
    screen_size: tuple[int, int] = (1080, 2400)
    connection_state: str = "connected"
    battery_level: int = 100
    is_charging: bool = False
    is_locked: bool = False
    current_package: str = ""
    current_activity: str = ""
    wifi_enabled: bool = True
    bluetooth_enabled: bool = False
    flashlight_on: bool = False
    mobile_data_enabled: bool = False
    volume_level: int = 50
    screen_on: bool = True
    location_enabled: bool = True
    network_state: str = "wifi"

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "android_version": self.android_version,
            "screen_size": f"{self.screen_size[0]}x{self.screen_size[1]}",
            "connection_state": self.connection_state,
            "battery_level": f"{self.battery_level}%",
            "is_charging": self.is_charging,
            "is_locked": self.is_locked,
            "current_package": self.current_package,
            "current_activity": self.current_activity,
            "wifi_enabled": self.wifi_enabled,
            "bluetooth_enabled": self.bluetooth_enabled,
            "flashlight_on": self.flashlight_on,
            "mobile_data_enabled": self.mobile_data_enabled,
            "volume_level": self.volume_level,
            "screen_on": self.screen_on,
            "location_enabled": self.location_enabled,
            "network_state": self.network_state,
        }


@dataclass
class AppInfo:
    """Information about an installed application."""
    name: str                           # Display name (e.g. "WhatsApp")
    package: str                        # Package name (e.g. "com.whatsapp")
    is_system: bool = False
    is_running: bool = False
    aliases: list[str] = field(default_factory=list)

    def matches(self, query: str) -> bool:
        q = query.strip().lower()
        if not q:
            return False
        if self.name.lower() == q:
            return True
        if self.package.lower() == q or self.package.lower().endswith(f".{q}"):
            return True
        if any(alias.lower() == q for alias in self.aliases):
            return True
        if q in self.name.lower():
            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "package": self.package,
            "is_system": self.is_system,
            "is_running": self.is_running,
            "aliases": self.aliases,
        }


@dataclass
class NotificationItem:
    """Structured representation of an active Android notification."""
    id: str
    package: str
    app_name: str = ""
    title: str = ""
    text: str = ""
    timestamp: float = field(default_factory=time.time)
    is_ongoing: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "package": self.package,
            "app_name": self.app_name,
            "title": self.title,
            "text": self.text,
            "is_ongoing": self.is_ongoing,
        }


@dataclass
class AndroidActionResult:
    """Structured result returned by Android actions."""
    success: bool
    action: str
    detail: str = ""
    verified: bool = False
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    # "state"    -> `verified` reflects a real post-action state check (e.g. flashlight readback).
    # "dispatch" -> the input event was only DISPATCHED. `verified` is the legacy "observe cycle ran"
    #               flag and must NOT be reported to the runtime as evidence that the effect happened.
    verification: str = "state"

    def to_dict(self) -> dict[str, Any]:
        res: dict[str, Any] = {
            "success": self.success,
            "action": self.action,
            "detail": self.detail,
            "verified": self.verified if self.verification == "state" else None,
            "verification": self.verification,
        }
        if self.verification != "state":
            res["dispatched"] = bool(self.success)
        if self.data:
            res["data"] = self.data
        if self.error:
            res["error"] = self.error
        return res
