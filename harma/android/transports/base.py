"""
Harma Android Transport Interface

Abstract base class for all Android transports (ADB, mock, emulator).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from harma.android.models import (
    AndroidDevice,
    DeviceStatus,
    NotificationItem,
)


class AndroidTransport(ABC):
    """
    Abstract interface for low-level Android communication.
    Implementations provide device connection, shell commands, screen capture,
    input events, and application lifecycle management.
    """

    @abstractmethod
    async def list_devices(self) -> list[AndroidDevice]:
        """Discover and return all connected Android devices."""

    @abstractmethod
    async def connect(self, device_id: Optional[str] = None) -> AndroidDevice:
        """Connect to a device by ID, or the default device if None."""

    @abstractmethod
    async def disconnect(self, device_id: Optional[str] = None) -> bool:
        """Disconnect from a device."""

    @abstractmethod
    async def get_device_info(self, device_id: str) -> dict[str, Any]:
        """Retrieve low-level hardware / OS info for a device."""

    @abstractmethod
    async def get_device_status(self, device_id: str) -> DeviceStatus:
        """Retrieve dynamic status (battery, screen size, current app, etc.)."""

    @abstractmethod
    async def capture_screenshot(self, device_id: str) -> bytes:
        """Capture screen as raw PNG bytes."""

    @abstractmethod
    async def get_ui_hierarchy(self, device_id: str) -> str:
        """Dump active window UI hierarchy as XML string."""

    @abstractmethod
    async def tap(self, device_id: str, x: int, y: int) -> bool:
        """Simulate single tap at (x, y) coordinates."""

    @abstractmethod
    async def long_press(self, device_id: str, x: int, y: int, duration_ms: int = 1000) -> bool:
        """Simulate long press at (x, y) coordinates."""

    @abstractmethod
    async def double_tap(self, device_id: str, x: int, y: int) -> bool:
        """Simulate double tap at (x, y) coordinates."""

    @abstractmethod
    async def swipe(
        self, device_id: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300
    ) -> bool:
        """Simulate swipe from (x1, y1) to (x2, y2)."""

    @abstractmethod
    async def drag(
        self, device_id: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 800
    ) -> bool:
        """Simulate drag operation."""

    @abstractmethod
    async def type_text(self, device_id: str, text: str) -> bool:
        """Type text into currently focused input field."""

    @abstractmethod
    async def press_key(self, device_id: str, key_code: str | int) -> bool:
        """Send keyevent (e.g. KEYCODE_BACK, KEYCODE_HOME, KEYCODE_ENTER)."""

    @abstractmethod
    async def list_packages(self, device_id: str) -> list[str]:
        """List all installed package names."""

    @abstractmethod
    async def get_current_app(self, device_id: str) -> tuple[str, str]:
        """Get (package_name, activity_name) of currently focused window."""

    @abstractmethod
    async def launch_app(self, device_id: str, package: str) -> bool:
        """Launch an application by package name."""

    @abstractmethod
    async def close_app(self, device_id: str, package: str) -> bool:
        """Force-stop an application by package name."""

    @abstractmethod
    async def get_clipboard(self, device_id: str) -> str:
        """Read device clipboard content."""

    @abstractmethod
    async def set_clipboard(self, device_id: str, text: str) -> bool:
        """Set device clipboard content."""

    @abstractmethod
    async def get_notifications(self, device_id: str) -> list[NotificationItem]:
        """Retrieve active status bar notifications."""

    @abstractmethod
    async def open_settings(self, device_id: str, panel: str = "general") -> bool:
        """Open system settings screen or sub-panel."""

    @abstractmethod
    async def is_locked(self, device_id: str) -> bool:
        """Return True if device screen is locked / keyguard active."""

    async def set_flashlight(self, device_id: str, enabled: bool) -> bool:
        """Toggle or set device flashlight/torch state."""
        return True

    async def get_flashlight(self, device_id: str) -> bool:
        """Query current flashlight state."""
        return False

    async def set_wifi(self, device_id: str, enabled: bool) -> tuple[bool, str]:
        """Enable or disable Wi-Fi. Returns (success, detail/fallback_action)."""
        return True, "Wi-Fi updated."

    async def get_wifi(self, device_id: str) -> bool:
        """Query Wi-Fi state."""
        return True

    async def set_mobile_data(self, device_id: str, enabled: bool) -> tuple[bool, str]:
        """
        Request mobile data state change.
        Under standard Android security, MODIFY_PHONE_STATE requires system/carrier permissions.
        Returns (success, reason_or_fallback).
        """
        return False, "settings_panel"

    async def get_mobile_data(self, device_id: str) -> bool:
        """Query mobile data state."""
        return False

    async def set_bluetooth(self, device_id: str, enabled: bool) -> tuple[bool, str]:
        """Toggle Bluetooth state."""
        return True, "Bluetooth updated."

    async def get_bluetooth(self, device_id: str) -> bool:
        """Query Bluetooth state."""
        return False

    async def set_volume(self, device_id: str, level: int, stream: str = "media") -> int:
        """Set volume level (0-100) on specified audio stream."""
        return max(0, min(100, level))

    async def get_volume(self, device_id: str, stream: str = "media") -> int:
        """Get volume level (0-100) on specified audio stream."""
        return 50

    async def navigate(self, device_id: str, destination: str) -> bool:
        """Launch navigation to destination in available map application."""
        return True

    async def open_camera(self, device_id: str) -> bool:
        """Launch camera app."""
        return True

    async def lock_device(self, device_id: str) -> bool:
        """Lock device screen."""
        return True

    async def unlock_device(self, device_id: str) -> bool:
        """Wake and unlock device screen."""
        return True

