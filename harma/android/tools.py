"""
Harma Android Tools

Registers all Android device automation tools into Harma's Tool Registry.
Fully integrated with the existing Permission System, ToolResult format,
and Agent Core.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from harma.android.exceptions import AndroidError
from harma.android.manager import AndroidManager, get_android_manager
from harma.config.logging_config import get_logger
from harma.tools.base import BaseTool, PermissionLevel, ToolResult

log = get_logger(__name__)


# ── Device & Screen Status Tools (SAFE) ───────────────────────────────────────

class AndroidDeviceStatusTool(BaseTool):
    """Inspect operational status of connected Android device."""

    name = "android.device_status"
    description = (
        "Get current status of the Android device including battery level, screen dimensions, "
        "connection state, Android OS version, model, and active foreground application."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "device_id": {
                "type": "string",
                "description": "Optional specific device ID. If omitted, uses default active device.",
            }
        },
    }

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, device_id: Optional[str] = None, **kwargs: Any) -> ToolResult:
        try:
            status = await self.manager.get_status(device_id=device_id)
            d = status.to_dict()
            return ToolResult(
                success=True,
                output=(
                    f"Android Device: {d['manufacturer']} {d['model']} (Android {d['android_version']})\n"
                    f"Screen: {d['screen_size']} | Battery: {d['battery_level']} (Charging: {d['is_charging']})\n"
                    f"Active App: {d['current_package']} | Screen Locked: {d['is_locked']}\n"
                    f"Wi-Fi: {d['wifi_enabled']} | Bluetooth: {d['bluetooth_enabled']}"
                ),
                data=d,
            )
        except AndroidError as exc:
            return ToolResult(
                success=False,
                output=f"Failed to get device status: {exc.message}",
                error=exc.code,
                data={"error": exc.code, "message": exc.message},
            )
        except Exception as exc:
            log.error("Unexpected error in android.device_status: %s", exc)
            return ToolResult(
                success=False,
                output="Device status inspection failed due to internal error.",
                error="DEVICE_STATUS_ERROR",
            )


class AndroidScreenshotTool(BaseTool):
    """Take a screenshot of the Android screen."""

    name = "android.screenshot"
    description = (
        "Capture the current Android screen and observe visible UI elements. "
        "Returns a structured summary of what is currently visible on the phone screen."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "device_id": {
                "type": "string",
                "description": "Optional device ID.",
            }
        },
    }

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, device_id: Optional[str] = None, **kwargs: Any) -> ToolResult:
        try:
            obs = await self.manager.screenshot(device_id=device_id)
            info = {
                "app": obs.current_package,
                "is_locked": obs.is_locked,
                "elements_count": len(obs.elements),
                "summary": obs.summary,
            }
            output = f"Current App: {obs.current_package}\n"
            if obs.is_locked:
                output += "⚠ Device is currently LOCKED.\n"
            output += f"Visible Elements ({len(obs.elements)}):\n{obs.summary}"

            return ToolResult(
                success=True,
                output=output,
                data=info,
            )
        except AndroidError as exc:
            return ToolResult(
                success=False,
                output=f"Screenshot failed: {exc.message}",
                error=exc.code,
                data={"error": exc.code, "message": exc.message},
            )
        except Exception as exc:
            log.error("Unexpected error in android.screenshot: %s", exc)
            return ToolResult(
                success=False,
                output="Failed to capture Android screenshot.",
                error="SCREENSHOT_ERROR",
            )


class AndroidObserveScreenTool(BaseTool):
    """Observe Android screen and return structured element hierarchy."""

    name = "android.observe_screen"
    description = (
        "Observe the current Android screen hierarchy and interactive UI elements. "
        "Use this before tapping or typing to see available buttons, text fields, and switches."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "device_id": {
                "type": "string",
                "description": "Optional device ID.",
            }
        },
    }

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, device_id: Optional[str] = None, **kwargs: Any) -> ToolResult:
        try:
            obs = await self.manager.observe_screen(device_id=device_id)
            return ToolResult(
                success=True,
                output=f"Active screen: {obs.current_package}\n{obs.summary}",
                data=obs.to_dict(),
            )
        except AndroidError as exc:
            return ToolResult(
                success=False,
                output=f"Screen observation failed: {exc.message}",
                error=exc.code,
                data={"error": exc.code, "message": exc.message},
            )


# ── App Management Tools ──────────────────────────────────────────────────────

class AndroidListAppsTool(BaseTool):
    """List installed applications on the Android device."""

    name = "android.list_apps"
    description = "List all installed applications on the Android device with display names and package identifiers."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "device_id": {
                "type": "string",
                "description": "Optional device ID.",
            }
        },
    }

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, device_id: Optional[str] = None, **kwargs: Any) -> ToolResult:
        try:
            apps = await self.manager.list_apps(device_id=device_id)
            names = [f"{a.name} ({a.package})" for a in apps[:30]]
            return ToolResult(
                success=True,
                output=f"Installed applications ({len(apps)} total):\n" + "\n".join(f"- {n}" for n in names),
                data={"apps": [a.to_dict() for a in apps]},
            )
        except AndroidError as exc:
            return ToolResult(
                success=False,
                output=f"Failed to list applications: {exc.message}",
                error=exc.code,
            )


class AndroidGetCurrentAppTool(BaseTool):
    """Get the currently focused foreground application."""

    name = "android.current_app"
    description = "Get the name and package of the application currently active on the Android phone screen."
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            app = await self.manager.get_current_app()
            return ToolResult(
                success=True,
                output=f"Currently active application: {app.name} ({app.package})",
                data=app.to_dict(),
            )
        except AndroidError as exc:
            return ToolResult(
                success=False,
                output=f"Failed to get current app: {exc.message}",
                error=exc.code,
            )


class AndroidLaunchAppTool(BaseTool):
    """Launch an application on Android."""

    name = "android.launch_app"
    description = (
        "Open or launch an application on the Android device by name (e.g. 'WhatsApp', 'Chrome', "
        "'Settings', 'YouTube') or package identifier."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "app_name": {
                "type": "string",
                "description": "Name or package of the app to launch (e.g. 'WhatsApp', 'Chrome', 'Settings').",
            },
            "device_id": {
                "type": "string",
                "description": "Optional device ID.",
            },
        },
        "required": ["app_name"],
    }

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, app_name: str, device_id: Optional[str] = None, **kwargs: Any) -> ToolResult:
        try:
            res = await self.manager.launch_app(app_name, device_id=device_id)
            return ToolResult(
                success=res.success,
                output=f"Launched '{app_name}' successfully." if res.success else f"Failed to launch '{app_name}'.",
                data=res.to_dict(),
            )
        except AndroidError as exc:
            return ToolResult(
                success=False,
                output=exc.message,
                error=exc.code,
                data={"error": exc.code, "message": exc.message},
            )


class AndroidCloseAppTool(BaseTool):
    """Close an application on Android."""

    name = "android.close_app"
    description = "Force close an application on the Android device by name or package identifier."
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "app_name": {
                "type": "string",
                "description": "Name or package of the app to close.",
            },
            "device_id": {
                "type": "string",
                "description": "Optional device ID.",
            },
        },
        "required": ["app_name"],
    }

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, app_name: str, device_id: Optional[str] = None, **kwargs: Any) -> ToolResult:
        try:
            res = await self.manager.close_app(app_name, device_id=device_id)
            return ToolResult(
                success=res.success,
                output=f"Closed '{app_name}'." if res.success else f"Failed to close '{app_name}'.",
                data=res.to_dict(),
            )
        except AndroidError as exc:
            return ToolResult(
                success=False,
                output=exc.message,
                error=exc.code,
            )


# ── Touch & Gesture Tools (SENSITIVE) ─────────────────────────────────────────

class AndroidTapTool(BaseTool):
    """Tap a UI element or coordinate on the Android screen."""

    name = "android.tap"
    description = (
        "Tap a button, link, or element on screen by its text, content description, or ID "
        "(e.g. 'Wi-Fi', 'Search', 'Send'). Can also tap at specific (x, y) coordinates."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Visible text, description, or resource ID of the element to tap.",
            },
            "x": {
                "type": "integer",
                "description": "Optional X coordinate if tapping by coordinates.",
            },
            "y": {
                "type": "integer",
                "description": "Optional Y coordinate if tapping by coordinates.",
            },
            "device_id": {
                "type": "string",
                "description": "Optional device ID.",
            },
        },
    }

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(
        self,
        target: Optional[str] = None,
        x: Optional[int] = None,
        y: Optional[int] = None,
        device_id: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            if x is not None and y is not None:
                res = await self.manager.tap(x, y=y, device_id=device_id)
            elif target:
                res = await self.manager.tap(target, device_id=device_id)
            else:
                return ToolResult(
                    success=False,
                    output="Must provide either element 'target' or ('x', 'y') coordinates.",
                    error="INVALID_ARGUMENTS",
                )

            return ToolResult(
                success=res.success,
                output=res.detail,
                data=res.to_dict(),
            )
        except AndroidError as exc:
            return ToolResult(
                success=False,
                output=exc.message,
                error=exc.code,
                data={"error": exc.code, "message": exc.message},
            )


class AndroidLongPressTool(BaseTool):
    """Long press at coordinates on the Android screen."""

    name = "android.long_press"
    description = "Long-press at screen coordinates (x, y) for a specified duration in milliseconds."
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "X coordinate."},
            "y": {"type": "integer", "description": "Y coordinate."},
            "duration_ms": {"type": "integer", "default": 1000, "description": "Duration in ms (default 1000)."},
        },
        "required": ["x", "y"],
    }

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, x: int, y: int, duration_ms: int = 1000, **kwargs: Any) -> ToolResult:
        try:
            res = await self.manager.long_press(x, y, duration_ms=duration_ms)
            return ToolResult(success=res.success, output=res.detail, data=res.to_dict())
        except AndroidError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


class AndroidSwipeTool(BaseTool):
    """Swipe across the Android screen."""

    name = "android.swipe"
    description = "Swipe from (x1, y1) to (x2, y2) on the Android screen."
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "x1": {"type": "integer"},
            "y1": {"type": "integer"},
            "x2": {"type": "integer"},
            "y2": {"type": "integer"},
            "duration_ms": {"type": "integer", "default": 300},
        },
        "required": ["x1", "y1", "x2", "y2"],
    }

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300, **kwargs: Any) -> ToolResult:
        try:
            res = await self.manager.swipe(x1, y1, x2, y2, duration_ms=duration_ms)
            return ToolResult(success=res.success, output=res.detail, data=res.to_dict())
        except AndroidError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


class AndroidScrollTool(BaseTool):
    """Scroll the Android screen in a direction."""

    name = "android.scroll"
    description = "Scroll the Android screen up, down, left, or right."
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "enum": ["up", "down", "left", "right"],
                "default": "down",
                "description": "Direction to scroll. 'down' reveals lower content.",
            },
            "distance": {
                "type": "integer",
                "default": 600,
                "description": "Scroll distance in pixels.",
            },
        },
    }

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, direction: str = "down", distance: int = 600, **kwargs: Any) -> ToolResult:
        try:
            res = await self.manager.scroll(direction=direction, distance_px=distance)
            return ToolResult(success=res.success, output=f"Scrolled {direction}.", data=res.to_dict())
        except AndroidError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


# ── Keyboard & Navigation Tools ───────────────────────────────────────────────

class AndroidTypeTool(BaseTool):
    """Type text into an active input field."""

    name = "android.type"
    description = "Type text into the currently focused input field on the Android device."
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text to type into the input field.",
            }
        },
        "required": ["text"],
    }

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, text: str, **kwargs: Any) -> ToolResult:
        try:
            res = await self.manager.type_text(text)
            return ToolResult(success=res.success, output=f"Typed text into input.", data=res.to_dict())
        except AndroidError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


class AndroidKeyPressTool(BaseTool):
    """Press a hardware or navigation key."""

    name = "android.press_key"
    description = "Press an Android key (ENTER, TAB, BACK, HOME, APP_SWITCH, DELETE, VOLUME_UP, VOLUME_DOWN)."
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Key identifier: ENTER, TAB, BACK, HOME, APP_SWITCH, DELETE, etc.",
            }
        },
        "required": ["key"],
    }

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, key: str, **kwargs: Any) -> ToolResult:
        try:
            res = await self.manager.press_key(key)
            return ToolResult(success=res.success, output=f"Pressed {key}.", data=res.to_dict())
        except AndroidError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


class AndroidHomeTool(BaseTool):
    """Go to Android Home screen."""

    name = "android.home"
    description = "Navigate to the Android Home screen."
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            res = await self.manager.home()
            return ToolResult(success=res.success, output="Navigated to Home screen.", data=res.to_dict())
        except AndroidError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


class AndroidBackTool(BaseTool):
    """Press Android Back button."""

    name = "android.back"
    description = "Press the Android Back button to navigate back or close dialogs."
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            res = await self.manager.back()
            return ToolResult(success=res.success, output="Navigated Back.", data=res.to_dict())
        except AndroidError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


class AndroidRecentAppsTool(BaseTool):
    """Open Recent Apps switcher."""

    name = "android.recent_apps"
    description = "Open the Android recent applications overview switcher."
    permission_level = PermissionLevel.SENSITIVE
    parameters = {"type": "object", "properties": {}}

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            res = await self.manager.recent_apps()
            return ToolResult(success=res.success, output="Opened recent applications.", data=res.to_dict())
        except AndroidError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


# ── System Features (Clipboard, Notifications, Settings) ──────────────────────

class AndroidGetClipboardTool(BaseTool):
    """Read clipboard content from Android device."""

    name = "android.get_clipboard"
    description = "Read current text from the Android device clipboard. Permission-controlled."
    permission_level = PermissionLevel.SENSITIVE
    parameters = {"type": "object", "properties": {}}

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            content = await self.manager.get_clipboard()
            return ToolResult(
                success=True,
                output=f"Clipboard content: {content}",
                data={"length": len(content)},
            )
        except AndroidError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


class AndroidSetClipboardTool(BaseTool):
    """Set text into Android clipboard."""

    name = "android.set_clipboard"
    description = "Copy text into the Android device clipboard."
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to place on clipboard."}
        },
        "required": ["text"],
    }

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, text: str, **kwargs: Any) -> ToolResult:
        try:
            res = await self.manager.set_clipboard(text)
            return ToolResult(success=res.success, output=res.detail, data=res.to_dict())
        except AndroidError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


class AndroidNotificationsTool(BaseTool):
    """Read active status bar notifications."""

    name = "android.notifications"
    description = "Inspect active Android system and app notifications."
    permission_level = PermissionLevel.SENSITIVE
    parameters = {"type": "object", "properties": {}}

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            notifs = await self.manager.get_notifications()
            if not notifs:
                return ToolResult(success=True, output="No active notifications.", data={"notifications": []})

            lines = [f"- [{n.app_name}] {n.title}: {n.text}" for n in notifs]
            return ToolResult(
                success=True,
                output=f"Active Notifications ({len(notifs)}):\n" + "\n".join(lines),
                data={"notifications": [n.to_dict() for n in notifs]},
            )
        except AndroidError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


class AndroidOpenSettingsTool(BaseTool):
    """Open Android settings screens."""

    name = "android.open_settings"
    description = (
        "Open Android Settings or a specific settings panel: 'general', 'wifi', "
        "'bluetooth', 'display', 'sound'."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "panel": {
                "type": "string",
                "enum": ["general", "wifi", "bluetooth", "display", "sound"],
                "default": "general",
                "description": "Settings panel to open.",
            }
        },
    }

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, panel: str = "general", **kwargs: Any) -> ToolResult:
        try:
            res = await self.manager.open_settings(panel=panel)
            return ToolResult(success=res.success, output=res.detail, data=res.to_dict())
        except AndroidError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


# ── System Capabilities: Flashlight, Network, Volume, Maps, Camera ──────────

class AndroidFlashlightTool(BaseTool):
    """Control the Android flashlight / torch."""

    name = "android.flashlight"
    description = "Turn the Android flashlight/torch on or off, or toggle its state."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "enabled": {
                "type": "boolean",
                "description": "True to turn on flashlight, False to turn off.",
            },
            "device_id": {
                "type": "string",
                "description": "Optional device ID.",
            },
        },
        "required": ["enabled"],
    }

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, enabled: bool = True, enable: Optional[bool] = None, device_id: Optional[str] = None, **kwargs: Any) -> ToolResult:
        on = enabled if enable is None else enable
        try:
            res = await self.manager.set_flashlight(enabled=on, device_id=device_id)
            return ToolResult(success=res.success, output=res.detail, data=res.to_dict())
        except AndroidError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


class AndroidWifiTool(BaseTool):
    """Enable or disable Android Wi-Fi."""

    name = "android.wifi"
    description = "Turn Android Wi-Fi on or off."
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "enabled": {
                "type": "boolean",
                "description": "True to enable Wi-Fi, False to disable.",
            },
            "device_id": {
                "type": "string",
                "description": "Optional device ID.",
            },
        },
        "required": ["enabled"],
    }

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, enabled: bool = True, enable: Optional[bool] = None, device_id: Optional[str] = None, **kwargs: Any) -> ToolResult:
        on = enabled if enable is None else enable
        try:
            res = await self.manager.set_wifi(enabled=on, device_id=device_id)
            return ToolResult(success=res.success, output=res.detail, data=res.to_dict())
        except AndroidError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


class AndroidMobileDataTool(BaseTool):
    """Manage Android Mobile Data state with platform settings fallback."""

    name = "android.mobile_data"
    description = (
        "Request mobile data state change. Because standard Android security restricts direct "
        "mobile data modification without carrier/system privileges, this tool either applies "
        "privileged change or opens the Internet settings panel so the user can toggle it."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "enabled": {
                "type": "boolean",
                "description": "True to enable mobile data, False to disable.",
            },
            "device_id": {
                "type": "string",
                "description": "Optional device ID.",
            },
        },
        "required": ["enabled"],
    }

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, enabled: bool = True, enable: Optional[bool] = None, device_id: Optional[str] = None, **kwargs: Any) -> ToolResult:
        on = enabled if enable is None else enable
        try:
            res = await self.manager.set_mobile_data(enabled=on, device_id=device_id)
            return ToolResult(success=res.success, output=res.detail, data=res.to_dict())
        except AndroidError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


class AndroidBluetoothTool(BaseTool):
    """Enable or disable Android Bluetooth."""

    name = "android.bluetooth"
    description = "Turn Android Bluetooth on or off."
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "enabled": {
                "type": "boolean",
                "description": "True to enable Bluetooth, False to disable.",
            },
            "device_id": {
                "type": "string",
                "description": "Optional device ID.",
            },
        },
        "required": ["enabled"],
    }

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, enabled: bool = True, enable: Optional[bool] = None, device_id: Optional[str] = None, **kwargs: Any) -> ToolResult:
        on = enabled if enable is None else enable
        try:
            res = await self.manager.set_bluetooth(enabled=on, device_id=device_id)
            return ToolResult(success=res.success, output=res.detail, data=res.to_dict())
        except AndroidError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


class AndroidVolumeTool(BaseTool):
    """Control Android audio volume."""

    name = "android.volume"
    description = "Set or adjust Android volume level (0-100) for media, ring, or alarm streams."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "level": {
                "type": "integer",
                "description": "Volume percentage from 0 to 100.",
            },
            "stream": {
                "type": "string",
                "enum": ["media", "ring", "alarm", "notification"],
                "default": "media",
                "description": "Audio stream to adjust.",
            },
            "device_id": {
                "type": "string",
                "description": "Optional device ID.",
            },
        },
        "required": ["level"],
    }

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, level: Optional[int] = None, stream: str = "media", action: str = "set", device_id: Optional[str] = None, **kwargs: Any) -> ToolResult:
        try:
            target_level = level if level is not None else kwargs.get("volume", 50)
            res = await self.manager.set_volume(level=target_level, stream=stream, device_id=device_id)
            return ToolResult(success=res.success, output=res.detail, data=res.to_dict())
        except AndroidError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


class AndroidNavigateTool(BaseTool):
    """Navigate to a location using Android Maps."""

    name = "android.navigate"
    description = "Open GPS navigation to a specified address or landmark using the device's map application."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "destination": {
                "type": "string",
                "description": "Destination address, place, or coordinates (e.g. 'Chennai Central').",
            },
            "device_id": {
                "type": "string",
                "description": "Optional device ID.",
            },
        },
        "required": ["destination"],
    }

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, destination: str, device_id: Optional[str] = None, **kwargs: Any) -> ToolResult:
        try:
            res = await self.manager.navigate(destination=destination, device_id=device_id)
            return ToolResult(success=res.success, output=res.detail, data=res.to_dict())
        except AndroidError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


class AndroidCameraTool(BaseTool):
    """Launch device camera application."""

    name = "android.camera"
    description = "Launch the Android camera application."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "device_id": {
                "type": "string",
                "description": "Optional device ID.",
            }
        },
    }

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, device_id: Optional[str] = None, **kwargs: Any) -> ToolResult:
        try:
            res = await self.manager.open_camera(device_id=device_id)
            return ToolResult(success=res.success, output=res.detail, data=res.to_dict())
        except AndroidError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


class AndroidLockTool(BaseTool):
    """Lock or unlock the Android screen."""

    name = "android.lock"
    description = "Lock or wake/unlock the Android device screen."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["lock", "unlock"],
                "default": "lock",
                "description": "Action to perform: 'lock' or 'unlock'.",
            },
            "device_id": {
                "type": "string",
                "description": "Optional device ID.",
            },
        },
    }

    def __init__(self, manager: Optional[AndroidManager] = None) -> None:
        self.manager = manager or get_android_manager()

    async def execute(self, action: str = "lock", device_id: Optional[str] = None, **kwargs: Any) -> ToolResult:
        try:
            if action == "unlock":
                res = await self.manager.unlock(device_id=device_id)
            else:
                res = await self.manager.lock(device_id=device_id)
            return ToolResult(success=res.success, output=res.detail, data=res.to_dict())
        except AndroidError as exc:
            return ToolResult(success=False, output=exc.message, error=exc.code)


def get_android_tools(manager: Optional[AndroidManager] = None) -> list[BaseTool]:
    """Return an instantiated list of all Android tools."""
    mgr = manager or get_android_manager()
    return [
        AndroidDeviceStatusTool(mgr),
        AndroidScreenshotTool(mgr),
        AndroidObserveScreenTool(mgr),
        AndroidListAppsTool(mgr),
        AndroidGetCurrentAppTool(mgr),
        AndroidLaunchAppTool(mgr),
        AndroidCloseAppTool(mgr),
        AndroidTapTool(mgr),
        AndroidLongPressTool(mgr),
        AndroidSwipeTool(mgr),
        AndroidScrollTool(mgr),
        AndroidTypeTool(mgr),
        AndroidKeyPressTool(mgr),
        AndroidHomeTool(mgr),
        AndroidBackTool(mgr),
        AndroidRecentAppsTool(mgr),
        AndroidGetClipboardTool(mgr),
        AndroidSetClipboardTool(mgr),
        AndroidNotificationsTool(mgr),
        AndroidOpenSettingsTool(mgr),
        AndroidFlashlightTool(mgr),
        AndroidWifiTool(mgr),
        AndroidMobileDataTool(mgr),
        AndroidBluetoothTool(mgr),
        AndroidVolumeTool(mgr),
        AndroidNavigateTool(mgr),
        AndroidCameraTool(mgr),
        AndroidLockTool(mgr),
    ]

