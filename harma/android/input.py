"""
Harma Android Input Controller

Handles touch actions (tap, long press, swipe, scroll), keyboard actions,
and robust element resolution with coordinate fallback.
"""

from __future__ import annotations

from typing import Optional

from harma.android.exceptions import (
    DeviceLockedError,
    ElementNotFoundError,
)
from harma.android.models import (
    AndroidActionResult,
    Bounds,
    ScreenObservation,
    UIElement,
)
from harma.android.transports.base import AndroidTransport
from harma.config.logging_config import get_logger

log = get_logger(__name__)

# Key codes for common Android actions
KEY_CODES = {
    "HOME": 3,
    "BACK": 4,
    "CALL": 5,
    "ENDCALL": 6,
    "VOLUME_UP": 24,
    "VOLUME_DOWN": 25,
    "POWER": 26,
    "CAMERA": 27,
    "CLEAR": 28,
    "COMMA": 55,
    "PERIOD": 56,
    "TAB": 61,
    "SPACE": 62,
    "ENTER": 66,
    "DELETE": 67,
    "APP_SWITCH": 187,   # Recent apps
    "NOTIFICATION": 83,
}


class InputController:
    """
    Manages all touch and keyboard interactions on the Android device.
    """

    def __init__(self, transport: AndroidTransport) -> None:
        self.transport = transport

    def resolve_element(
        self,
        observation: ScreenObservation,
        query: str,
    ) -> Optional[UIElement]:
        """
        Resolve a UI element from screen observation by applying resolution priority:
          1. Resource ID
          2. Accessibility ID / content-description
          3. Visible text (exact match)
          4. Visible text (case-insensitive)
          5. Visible text / description (contains / substring)
          6. Role / Class
        """
        return observation.find_element(query)

    async def tap(
        self,
        device_id: str,
        x: int,
        y: int,
        observation: Optional[ScreenObservation] = None,
    ) -> AndroidActionResult:
        """Tap at screen coordinates (x, y)."""
        if observation and (x > observation.width or y > observation.height or x < 0 or y < 0):
            log.warning("Tap coordinates (%d, %d) outside screen bounds %dx%d", x, y, observation.width, observation.height)

        success = await self.transport.tap(device_id, x, y)
        return AndroidActionResult(
            success=success,
            action="tap",
            detail=f"Tapped at coordinate ({x}, {y})",
            verified=True,
            verification="dispatch",
            data={"x": x, "y": y},
        )

    async def tap_element(
        self,
        device_id: str,
        observation: ScreenObservation,
        query: str,
    ) -> AndroidActionResult:
        """
        Locate element by query and tap its center point.
        """
        element = self.resolve_element(observation, query)
        if not element:
            raise ElementNotFoundError(query)

        cx, cy = element.center
        success = await self.transport.tap(device_id, cx, cy)
        label = element.text or element.content_description or element.id or element.simple_role

        return AndroidActionResult(
            success=success,
            action="tap_element",
            detail=f"Tapped element '{label}' at ({cx}, {cy})",
            verified=True,
            verification="dispatch",
            data={"element": element.to_dict(), "center": (cx, cy)},
        )

    async def long_press(
        self,
        device_id: str,
        x: int,
        y: int,
        duration_ms: int = 1000,
    ) -> AndroidActionResult:
        """Execute a long press at coordinates."""
        success = await self.transport.long_press(device_id, x, y, duration_ms=duration_ms)
        return AndroidActionResult(
            success=success,
            action="long_press",
            detail=f"Long-pressed at ({x}, {y}) for {duration_ms}ms",
            verified=True,
            verification="dispatch",
            data={"x": x, "y": y, "duration_ms": duration_ms},
        )

    async def double_tap(self, device_id: str, x: int, y: int) -> AndroidActionResult:
        """Execute a double tap at coordinates."""
        success = await self.transport.double_tap(device_id, x, y)
        return AndroidActionResult(
            success=success,
            action="double_tap",
            detail=f"Double-tapped at ({x}, {y})",
            verified=True,
            verification="dispatch",
            data={"x": x, "y": y},
        )

    async def swipe(
        self,
        device_id: str,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
    ) -> AndroidActionResult:
        """Execute a swipe gesture from (x1, y1) to (x2, y2)."""
        success = await self.transport.swipe(device_id, x1, y1, x2, y2, duration_ms)
        return AndroidActionResult(
            success=success,
            action="swipe",
            detail=f"Swiped from ({x1}, {y1}) to ({x2}, {y2})",
            verified=True,
            verification="dispatch",
            data={"from": (x1, y1), "to": (x2, y2), "duration_ms": duration_ms},
        )

    async def scroll(
        self,
        device_id: str,
        direction: str = "down",
        distance_px: int = 600,
        screen_size: tuple[int, int] = (1080, 2400),
    ) -> AndroidActionResult:
        """
        Scroll screen in specified direction ('up', 'down', 'left', 'right').
        'down' scrolls down to reveal lower content (swipes up).
        'up' scrolls up to reveal higher content (swipes down).
        """
        w, h = screen_size
        mid_x = w // 2
        mid_y = h // 2

        if direction.lower() == "down":
            x1, y1 = mid_x, mid_y + (distance_px // 2)
            x2, y2 = mid_x, mid_y - (distance_px // 2)
        elif direction.lower() == "up":
            x1, y1 = mid_x, mid_y - (distance_px // 2)
            x2, y2 = mid_x, mid_y + (distance_px // 2)
        elif direction.lower() == "right":
            x1, y1 = mid_x + (distance_px // 2), mid_y
            x2, y2 = mid_x - (distance_px // 2), mid_y
        elif direction.lower() == "left":
            x1, y1 = mid_x - (distance_px // 2), mid_y
            x2, y2 = mid_x + (distance_px // 2), mid_y
        else:
            x1, y1 = mid_x, mid_y + (distance_px // 2)
            x2, y2 = mid_x, mid_y - (distance_px // 2)

        return await self.swipe(device_id, x1, y1, x2, y2, duration_ms=300)

    async def drag(
        self,
        device_id: str,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 800,
    ) -> AndroidActionResult:
        """Drag from (x1, y1) to (x2, y2)."""
        success = await self.transport.drag(device_id, x1, y1, x2, y2, duration_ms)
        return AndroidActionResult(
            success=success,
            action="drag",
            detail=f"Dragged from ({x1}, {y1}) to ({x2}, {y2})",
            verified=True,
            verification="dispatch",
            data={"from": (x1, y1), "to": (x2, y2), "duration_ms": duration_ms},
        )

    async def type_text(self, device_id: str, text: str) -> AndroidActionResult:
        """Type text into currently focused input."""
        success = await self.transport.type_text(device_id, text)
        return AndroidActionResult(
            success=success,
            action="type_text",
            detail=f"Typed text: '{text}'",
            verified=True,
            verification="dispatch",
            data={"text": text},
        )

    async def press_key(self, device_id: str, key: str | int) -> AndroidActionResult:
        """Send keyevent (e.g. 'ENTER', 'BACK', 'HOME', 66)."""
        code = key
        if isinstance(key, str):
            code = KEY_CODES.get(key.upper(), key)

        success = await self.transport.press_key(device_id, code)
        return AndroidActionResult(
            success=success,
            action="press_key",
            detail=f"Pressed key '{key}'",
            verified=True,
            verification="dispatch",
            data={"key": str(key), "code": str(code)},
        )

    async def home(self, device_id: str) -> AndroidActionResult:
        """Navigate to Android Home screen."""
        return await self.press_key(device_id, KEY_CODES["HOME"])

    async def back(self, device_id: str) -> AndroidActionResult:
        """Navigate Back."""
        return await self.press_key(device_id, KEY_CODES["BACK"])

    async def recent_apps(self, device_id: str) -> AndroidActionResult:
        """Open recent apps switcher."""
        return await self.press_key(device_id, KEY_CODES["APP_SWITCH"])
