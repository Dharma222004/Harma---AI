"""
Harma Android Manager

Central orchestrator for the Android subsystem. Coordinates device connection,
screen observation, element resolution, touch/keyboard input, apps, clipboard,
and Observe → Act → Verify action cycles.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from harma.android.apps import AppManager
from harma.android.clipboard import ClipboardManager
from harma.android.device import DeviceController
from harma.android.exceptions import (
    ActionTimeoutError,
    AndroidError,
    DeviceLockedError,
    ElementNotFoundError,
    SecurityRestrictionError,
)
from harma.android.input import InputController
from harma.android.models import (
    AndroidActionResult,
    AndroidDevice,
    AppInfo,
    DeviceStatus,
    NotificationItem,
    ScreenObservation,
    UIElement,
)
from harma.android.notifications import NotificationManager
from harma.android.permissions import AndroidSecurity
from harma.android.screen import ScreenObserver
from harma.android.transports.base import AndroidTransport
from harma.config.logging_config import get_logger
from harma.config.settings import config

log = get_logger(__name__)


class AndroidManager:
    """
    Primary API entry point for Android control.
    Coordinates all Android sub-components and executes Observe → Act → Verify cycles.
    """

    def __init__(
        self,
        transport: Optional[AndroidTransport] = None,
        auto_connect: bool = True,
    ) -> None:
        if transport is None:
            # Select transport based on config or availability
            from harma.android.transports.adb import ADBTransport
            from harma.android.transports.mock import FakeAndroidTransport

            adb = ADBTransport()
            if adb.check_adb_available():
                self.transport: AndroidTransport = adb
            else:
                log.info("ADB not available; defaulting AndroidManager to FakeAndroidTransport")
                self.transport = FakeAndroidTransport()
        else:
            self.transport = transport

        self.device_controller = DeviceController(self.transport)
        self.screen_observer = ScreenObserver(self.transport)
        self.input_controller = InputController(self.transport)
        self.app_manager = AppManager(self.transport)
        self.clipboard_manager = ClipboardManager(self.transport)
        self.notification_manager = NotificationManager(self.transport)
        self.security = AndroidSecurity()

        self._last_observation: Optional[ScreenObservation] = None
        self._auto_connect = auto_connect

    async def _get_device_id(self, device_id: Optional[str] = None) -> str:
        """Resolve target device ID and ensure connected."""
        target_id = await self.device_controller.resolve_target_device(device_id)
        if self._auto_connect and not self.device_controller.active_device:
            await self.device_controller.connect(target_id)
        return target_id

    # ── Device Lifecycle & Status ─────────────────────────────────────────────

    async def list_devices(self) -> list[AndroidDevice]:
        return await self.device_controller.list_devices()

    async def connect(self, device_id: Optional[str] = None) -> AndroidDevice:
        return await self.device_controller.connect(device_id)

    async def disconnect(self, device_id: Optional[str] = None) -> bool:
        return await self.device_controller.disconnect(device_id)

    async def get_status(self, device_id: Optional[str] = None) -> DeviceStatus:
        target_id = await self._get_device_id(device_id)
        return await self.device_controller.get_status(target_id)

    # ── Screen Observation ───────────────────────────────────────────────────

    async def observe_screen(
        self, device_id: Optional[str] = None, force_refresh: bool = False
    ) -> ScreenObservation:
        """
        Capture and return current screen observation (hierarchy + screenshot).
        """
        target_id = await self._get_device_id(device_id)
        t0 = time.time()
        obs = await self.screen_observer.observe(target_id)
        self._last_observation = obs
        elapsed_ms = int((time.time() - t0) * 1000)
        log.info(
            "ANDROID_SCREEN_CAPTURED device_id=%s elements=%d latency=%dms",
            target_id,
            len(obs.elements),
            elapsed_ms,
        )
        return obs

    async def screenshot(self, device_id: Optional[str] = None) -> ScreenObservation:
        """Alias for observe_screen."""
        return await self.observe_screen(device_id=device_id)

    async def observe_ui(self, device_id: Optional[str] = None) -> ScreenObservation:
        """
        Observe the UI hierarchy only (no screenshot, no image upload) — the strongest cheap evidence.
        Observation priority: accessibility / UI hierarchy first; screenshots only on explicit request.
        """
        target_id = await self._get_device_id(device_id)
        shot_flag = self.screen_observer.include_screenshots
        self.screen_observer.include_screenshots = False
        try:
            obs = await self.screen_observer.observe(target_id)
        finally:
            self.screen_observer.include_screenshots = shot_flag
        self._last_observation = obs
        return obs

    # ── Observe → Act → Verify Actions ───────────────────────────────────────

    async def tap(
        self,
        target: str | tuple[int, int] | int,
        y: Optional[int] = None,
        device_id: Optional[str] = None,
        verify: bool = True,
    ) -> AndroidActionResult:
        """
        Tap either an element by query string (e.g. 'Wi-Fi') or (x, y) coordinates.
        Follows Observe → Act → Verify pattern.
        """
        target_id = await self._get_device_id(device_id)

        # 1. Coordinate-based tap
        if isinstance(target, (int, float)) and y is not None:
            x_coord = int(target)
            y_coord = int(y)
            log.info("ANDROID_ACTION_STARTED action=tap coords=(%d, %d)", x_coord, y_coord)
            res = await self.input_controller.tap(target_id, x_coord, y_coord)
            log.info("ANDROID_ACTION_COMPLETED action=tap verified=%s", res.verified)
            return res

        elif isinstance(target, tuple) and len(target) == 2:
            x_coord, y_coord = target
            res = await self.input_controller.tap(target_id, int(x_coord), int(y_coord))
            return res

        # 2. Element-based tap with Observe → Act → Verify
        query = str(target).strip()
        self.security.validate_action_safety("tap", query)

        log.info("ANDROID_ACTION_STARTED action=tap_element query=%r", query)
        obs = await self.observe_screen(target_id)

        if obs.is_locked:
            raise DeviceLockedError()

        element = self.input_controller.resolve_element(obs, query)

        # Retry once if element not found initially
        if not element:
            log.debug("Element %r not found on initial observation, retrying once...", query)
            await asyncio.sleep(0.5)
            obs = await self.observe_screen(target_id, force_refresh=True)
            element = self.input_controller.resolve_element(obs, query)

        if not element:
            log.warning("ANDROID_ELEMENT_NOT_FOUND query=%r", query)
            raise ElementNotFoundError(query)

        log.info(
            "ANDROID_ELEMENT_FOUND query=%r id=%r center=%s",
            query,
            element.id,
            element.center,
        )

        res = await self.input_controller.tap_element(target_id, obs, query)

        if verify:
            await asyncio.sleep(0.3)
            new_obs = await self.observe_screen(target_id)
            # Legacy flag only: the screen was re-observed. Whether the tap had its intended effect
            # is NOT established here (verification stays "dispatch").
            res.verified = True
            res.verification = "dispatch"
            res.data["post_action_screen"] = new_obs.current_package

        log.info("ANDROID_ACTION_COMPLETED action=tap_element query=%r verified=%s", query, res.verified)
        return res

    async def tap_element(
        self,
        target_or_device: Any,
        obs_or_target: Any = None,
        query: Optional[str] = None,
        **kwargs: Any,
    ) -> AndroidActionResult:
        """Tap a UI element by query or delegate to input_controller."""
        if query is not None and isinstance(obs_or_target, ScreenObservation):
            return await self.input_controller.tap_element(str(target_or_device), obs_or_target, query)
        target = query or obs_or_target or target_or_device
        return await self.tap(target, **kwargs)

    async def long_press(
        self,
        x: int,
        y: int,
        duration_ms: int = 1000,
        device_id: Optional[str] = None,
    ) -> AndroidActionResult:
        target_id = await self._get_device_id(device_id)
        return await self.input_controller.long_press(target_id, x, y, duration_ms)

    async def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
        device_id: Optional[str] = None,
    ) -> AndroidActionResult:
        target_id = await self._get_device_id(device_id)
        return await self.input_controller.swipe(target_id, x1, y1, x2, y2, duration_ms)

    async def scroll(
        self,
        direction: str = "down",
        distance_px: int = 600,
        device_id: Optional[str] = None,
    ) -> AndroidActionResult:
        target_id = await self._get_device_id(device_id)
        status = await self.device_controller.get_status(target_id)
        return await self.input_controller.scroll(
            target_id, direction, distance_px, screen_size=status.screen_size
        )

    async def type_text(
        self,
        text: str,
        device_id: Optional[str] = None,
    ) -> AndroidActionResult:
        """Type text into active input field."""
        self.security.validate_action_safety("type_text", text)
        target_id = await self._get_device_id(device_id)
        return await self.input_controller.type_text(target_id, text)

    async def press_key(
        self,
        key: str | int,
        device_id: Optional[str] = None,
    ) -> AndroidActionResult:
        target_id = await self._get_device_id(device_id)
        return await self.input_controller.press_key(target_id, key)

    async def home(self, device_id: Optional[str] = None) -> AndroidActionResult:
        target_id = await self._get_device_id(device_id)
        return await self.input_controller.home(target_id)

    async def back(self, device_id: Optional[str] = None) -> AndroidActionResult:
        target_id = await self._get_device_id(device_id)
        return await self.input_controller.back(target_id)

    async def recent_apps(self, device_id: Optional[str] = None) -> AndroidActionResult:
        target_id = await self._get_device_id(device_id)
        return await self.input_controller.recent_apps(target_id)

    # ── App Management ───────────────────────────────────────────────────────

    async def list_apps(self, device_id: Optional[str] = None) -> list[AppInfo]:
        target_id = await self._get_device_id(device_id)
        return await self.app_manager.list_installed_apps(target_id)

    async def launch_app(
        self,
        app_name_or_package: str,
        device_id: Optional[str] = None,
    ) -> AndroidActionResult:
        self.security.validate_action_safety("launch_app", app_name_or_package)
        target_id = await self._get_device_id(device_id)
        log.info("ANDROID_ACTION_STARTED action=launch_app app=%s", app_name_or_package)
        res = await self.app_manager.launch_app(target_id, app_name_or_package)
        log.info(
            "ANDROID_APP_LAUNCHED app=%s package=%s verified=%s",
            app_name_or_package,
            res.data.get("package"),
            res.verified,
        )
        return res

    async def close_app(
        self,
        app_name_or_package: str,
        device_id: Optional[str] = None,
    ) -> AndroidActionResult:
        self.security.validate_action_safety("close_app", app_name_or_package)
        target_id = await self._get_device_id(device_id)
        return await self.app_manager.close_app(target_id, app_name_or_package)

    async def get_current_app(self, device_id: Optional[str] = None) -> AppInfo:
        target_id = await self._get_device_id(device_id)
        return await self.app_manager.get_current_app(target_id)

    # ── Clipboard & Notifications ─────────────────────────────────────────────

    async def get_clipboard(self, device_id: Optional[str] = None) -> str:
        target_id = await self._get_device_id(device_id)
        return await self.clipboard_manager.get_clipboard(target_id)

    async def set_clipboard(
        self, text: str, device_id: Optional[str] = None
    ) -> AndroidActionResult:
        target_id = await self._get_device_id(device_id)
        return await self.clipboard_manager.set_clipboard(target_id, text)

    async def get_notifications(
        self, device_id: Optional[str] = None
    ) -> list[NotificationItem]:
        target_id = await self._get_device_id(device_id)
        return await self.notification_manager.get_notifications(target_id)

    async def open_settings(
        self, panel: str = "general", device_id: Optional[str] = None
    ) -> AndroidActionResult:
        target_id = await self._get_device_id(device_id)
        success = await self.transport.open_settings(target_id, panel=panel)
        return AndroidActionResult(
            success=success,
            action="open_settings",
            detail=f"Opened settings ({panel})",
            verified=True,
            verification="dispatch",
            data={"panel": panel},
        )

    # ── System Capabilities (Spec §16 - §23) ──────────────────────────────────

    async def set_flashlight(self, enabled: bool, device_id: Optional[str] = None) -> AndroidActionResult:
        target_id = await self._get_device_id(device_id)
        success = await self.transport.set_flashlight(target_id, enabled)
        actual = await self.transport.get_flashlight(target_id)
        verified = (actual == enabled)
        state_str = "ON" if enabled else "OFF"
        return AndroidActionResult(
            success=success,
            action="flashlight",
            detail=f"Flashlight turned {state_str}.",
            verified=verified,
            data={"flashlight_on": actual},
        )

    async def get_flashlight(self, device_id: Optional[str] = None) -> bool:
        target_id = await self._get_device_id(device_id)
        return await self.transport.get_flashlight(target_id)

    async def set_wifi(self, enabled: bool, device_id: Optional[str] = None) -> AndroidActionResult:
        target_id = await self._get_device_id(device_id)
        success, detail = await self.transport.set_wifi(target_id, enabled)
        actual = await self.transport.get_wifi(target_id)
        verified = (actual == enabled)
        return AndroidActionResult(
            success=success,
            action="wifi",
            detail=detail,
            verified=verified,
            data={"wifi_enabled": actual},
        )

    async def get_wifi(self, device_id: Optional[str] = None) -> bool:
        target_id = await self._get_device_id(device_id)
        return await self.transport.get_wifi(target_id)

    async def set_mobile_data(self, enabled: bool, device_id: Optional[str] = None) -> AndroidActionResult:
        target_id = await self._get_device_id(device_id)
        success, fallback = await self.transport.set_mobile_data(target_id, enabled)
        if not success and fallback == "settings_panel":
            # Spec §17: Android requires MODIFY_PHONE_STATE. Fallback to settings panel without false reporting.
            detail = "I can't directly change mobile data on this device. I'll open the Internet settings so you can enable it."
            await self.transport.open_settings(target_id, panel="wifi")
            return AndroidActionResult(
                success=True,
                action="mobile_data_fallback",
                detail=detail,
                verified=True,
                verification="dispatch",
                data={"fallback": "settings_panel", "direct_modification_supported": False},
            )
        actual = await self.transport.get_mobile_data(target_id)
        return AndroidActionResult(
            success=success,
            action="mobile_data",
            detail=f"Mobile data {'enabled' if enabled else 'disabled'}.",
            verified=(actual == enabled),
            data={"mobile_data_enabled": actual},
        )

    async def get_mobile_data(self, device_id: Optional[str] = None) -> bool:
        target_id = await self._get_device_id(device_id)
        return await self.transport.get_mobile_data(target_id)

    async def set_bluetooth(self, enabled: bool, device_id: Optional[str] = None) -> AndroidActionResult:
        target_id = await self._get_device_id(device_id)
        success, detail = await self.transport.set_bluetooth(target_id, enabled)
        actual = await self.transport.get_bluetooth(target_id)
        return AndroidActionResult(
            success=success,
            action="bluetooth",
            detail=detail,
            verified=(actual == enabled),
            data={"bluetooth_enabled": actual},
        )

    async def get_bluetooth(self, device_id: Optional[str] = None) -> bool:
        target_id = await self._get_device_id(device_id)
        return await self.transport.get_bluetooth(target_id)

    async def set_volume(self, level: int, stream: str = "media", device_id: Optional[str] = None) -> AndroidActionResult:
        target_id = await self._get_device_id(device_id)
        new_level = await self.transport.set_volume(target_id, level, stream=stream)
        actual = await self.transport.get_volume(target_id, stream=stream)
        return AndroidActionResult(
            success=True,
            action="volume",
            detail=f"Set {stream} volume to {new_level}%.",
            verified=(actual == new_level),
            data={"volume_level": actual, "stream": stream},
        )

    async def get_volume(self, stream: str = "media", device_id: Optional[str] = None) -> int:
        target_id = await self._get_device_id(device_id)
        return await self.transport.get_volume(target_id, stream=stream)

    async def navigate(self, destination: str, device_id: Optional[str] = None) -> AndroidActionResult:
        target_id = await self._get_device_id(device_id)
        success = await self.transport.navigate(target_id, destination=destination)
        return AndroidActionResult(
            success=success,
            action="navigate",
            detail=f"Navigating to '{destination}' via maps.",
            verified=success,
            verification="dispatch",
            data={"destination": destination},
        )

    async def open_camera(self, device_id: Optional[str] = None) -> AndroidActionResult:
        target_id = await self._get_device_id(device_id)
        success = await self.transport.open_camera(target_id)
        return AndroidActionResult(
            success=success,
            action="open_camera",
            detail="Opened camera.",
            verified=success,
            verification="dispatch",
        )

    async def lock(self, device_id: Optional[str] = None) -> AndroidActionResult:
        target_id = await self._get_device_id(device_id)
        res = self.transport.lock_device(target_id)
        if asyncio.iscoroutine(res):
            success = await res
        else:
            success = bool(res)
        return AndroidActionResult(
            success=success,
            action="lock",
            detail="Locked phone screen.",
            verified=success,
        )

    async def unlock(self, device_id: Optional[str] = None) -> AndroidActionResult:
        target_id = await self._get_device_id(device_id)
        res = self.transport.unlock_device(target_id)
        if asyncio.iscoroutine(res):
            success = await res
        else:
            success = bool(res)
        return AndroidActionResult(
            success=success,
            action="unlock",
            detail="Unlocked phone screen.",
            verified=success,
        )

    async def get_device_status(self, device_id: Optional[str] = None) -> DeviceStatus:
        target_id = await self._get_device_id(device_id)
        return await self.transport.get_device_status(target_id)



# Singleton instance accessor
_global_android_manager: Optional[AndroidManager] = None


def get_android_manager() -> AndroidManager:
    """Return active AndroidManager singleton."""
    global _global_android_manager
    if _global_android_manager is None:
        _global_android_manager = AndroidManager()
    return _global_android_manager


def set_android_manager(manager: AndroidManager) -> None:
    """Override AndroidManager instance (used in tests with FakeAndroidTransport)."""
    global _global_android_manager
    _global_android_manager = manager
