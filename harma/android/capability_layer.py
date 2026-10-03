"""
Harma Android — Capability Layer (Spec §13, §14, §15, §16-§23)

Direct capability layer connecting the Harma Runtime to Android system controls,
device APIs, intents, and accessibility actions.

Action Priority (Spec §14):
    1. Direct public Android API / System control
    2. Explicit Android Intent
    3. App-specific supported API
    4. Accessibility / UI automation
    5. UI interaction
    6. ADB / transport
"""

from __future__ import annotations

from typing import Any, Optional

from harma.android.manager import AndroidManager, get_android_manager
from harma.android.models import AndroidActionResult, DeviceStatus
from harma.config.logging_config import get_logger

log = get_logger(__name__)


class AndroidCapabilityLayer:
    """
    Unified high-level interface for Android capabilities.
    Used by HarmaRunner, StrategySelector, and the ToolRuntime.
    """

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def get_device_state(self, device_id: Optional[str] = None) -> DeviceStatus:
        """Fetch comprehensive operational state of the device."""
        return await self.manager.get_status(device_id=device_id)

    # ── System Controls ───────────────────────────────────────────────────────

    async def set_flashlight(self, enabled: bool, device_id: Optional[str] = None) -> AndroidActionResult:
        """Control torch state and verify."""
        log.info("[ANDROID-CAP] set_flashlight enabled=%s", enabled)
        return await self.manager.set_flashlight(enabled=enabled, device_id=device_id)

    async def set_wifi(self, enabled: bool, device_id: Optional[str] = None) -> AndroidActionResult:
        """Control Wi-Fi and verify."""
        log.info("[ANDROID-CAP] set_wifi enabled=%s", enabled)
        return await self.manager.set_wifi(enabled=enabled, device_id=device_id)

    async def set_mobile_data(self, enabled: bool, device_id: Optional[str] = None) -> AndroidActionResult:
        """
        Request mobile data change.
        Under standard Android security, provides settings panel fallback without false reporting.
        """
        log.info("[ANDROID-CAP] set_mobile_data enabled=%s", enabled)
        return await self.manager.set_mobile_data(enabled=enabled, device_id=device_id)

    async def set_bluetooth(self, enabled: bool, device_id: Optional[str] = None) -> AndroidActionResult:
        """Control Bluetooth state."""
        log.info("[ANDROID-CAP] set_bluetooth enabled=%s", enabled)
        return await self.manager.set_bluetooth(enabled=enabled, device_id=device_id)

    async def set_volume(
        self, level: int, stream: str = "media", device_id: Optional[str] = None
    ) -> AndroidActionResult:
        """Set volume level (0-100) and verify."""
        log.info("[ANDROID-CAP] set_volume level=%s stream=%s", level, stream)
        return await self.manager.set_volume(level=level, stream=stream, device_id=device_id)

    async def adjust_volume(
        self, delta: int, stream: str = "media", device_id: Optional[str] = None
    ) -> AndroidActionResult:
        """Increase or decrease volume by relative delta."""
        status = await self.get_device_state(device_id=device_id)
        current = status.volume_level
        new_level = max(0, min(100, current + delta))
        return await self.set_volume(level=new_level, stream=stream, device_id=device_id)

    # ── Navigation & Apps ─────────────────────────────────────────────────────

    async def navigate(self, destination: str, device_id: Optional[str] = None) -> AndroidActionResult:
        """Launch navigation to destination via maps application."""
        log.info("[ANDROID-CAP] navigate destination=%r", destination)
        return await self.manager.navigate(destination=destination, device_id=device_id)

    async def open_application(self, app_name: str, device_id: Optional[str] = None) -> AndroidActionResult:
        """Launch application by name or package."""
        log.info("[ANDROID-CAP] open_application app_name=%r", app_name)
        return await self.manager.launch_app(app_name, device_id=device_id)

    async def close_application(self, app_name: str, device_id: Optional[str] = None) -> AndroidActionResult:
        """Force-stop application by name or package."""
        log.info("[ANDROID-CAP] close_application app_name=%r", app_name)
        return await self.manager.close_app(app_name, device_id=device_id)

    async def open_camera(self, device_id: Optional[str] = None) -> AndroidActionResult:
        """Launch camera application."""
        log.info("[ANDROID-CAP] open_camera")
        return await self.manager.open_camera(device_id=device_id)

    # ── Screen & Navigation ───────────────────────────────────────────────────

    async def home(self, device_id: Optional[str] = None) -> AndroidActionResult:
        return await self.manager.home(device_id=device_id)

    async def back(self, device_id: Optional[str] = None) -> AndroidActionResult:
        return await self.manager.back(device_id=device_id)

    async def lock(self, device_id: Optional[str] = None) -> AndroidActionResult:
        return await self.manager.lock(device_id=device_id)

    async def unlock(self, device_id: Optional[str] = None) -> AndroidActionResult:
        return await self.manager.unlock(device_id=device_id)
