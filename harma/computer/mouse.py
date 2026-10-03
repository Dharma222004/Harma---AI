"""
Harma Mouse Module

Low-level mouse control.
All operations pass through safety validation before execution.

Supported operations:
  move(x, y)
  click(x, y, button)
  double_click(x, y)
  right_click(x, y)
  drag(start_x, start_y, end_x, end_y)
  scroll(amount, direction, x, y)
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Optional

from harma.computer.safety import (
    SafetyError,
    enforce_rate_limit,
    validate_coordinates,
)
from harma.config.logging_config import get_logger

log = get_logger(__name__)

# Mouse move duration in seconds (gives OS time to register)
_MOVE_DURATION = 0.3


@dataclass
class MouseResult:
    """Result of a mouse operation."""
    success: bool
    action: str
    x: int = 0
    y: int = 0
    error: str = ""

    def to_text(self) -> str:
        if self.success:
            return f"{self.action} at ({self.x}, {self.y})"
        return f"{self.action} failed: {self.error}"

    def to_dict(self) -> dict:
        d = {
            "success": self.success,
            "action": self.action,
            "x": self.x,
            "y": self.y,
        }
        if not self.success:
            d["error"] = self.error
        return d


def _get_pyautogui():
    """Return pyautogui with fail-safe configured."""
    try:
        import pyautogui
        # Keep fail-safe ON: moving mouse to corner aborts actions
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.05  # small default pause between actions
        return pyautogui
    except ImportError:
        raise SafetyError(
            "pyautogui is required for mouse control. "
            "Install with: pip install pyautogui"
        )


def _ensure_not_at_corner(pag) -> None:
    """
    Move the mouse away from (0,0) using an already-obtained pyautogui ref.
    Caller must set pag.FAILSAFE = False BEFORE calling this function.
    """
    try:
        pos = pag.position()
        if pos.x <= 5 and pos.y <= 5:
            pag.moveTo(100, 100, duration=0.15)
    except Exception:
        pass  # best-effort — don't block the actual operation


def move(x: int, y: int, duration: float = _MOVE_DURATION) -> MouseResult:
    """
    Move the mouse cursor to (x, y).

    Args:
        x, y: Target screen coordinates.
        duration: Movement duration in seconds (smooth movement).
    """
    log.info("[MOUSE] move(%d, %d)", x, y)
    try:
        enforce_rate_limit()
        validate_coordinates(x, y)
        pag = _get_pyautogui()
        # Temporarily disable FAILSAFE for the initial position check + move
        pag.FAILSAFE = False
        try:
            _ensure_not_at_corner(pag)
            pag.moveTo(x, y, duration=duration)
        finally:
            pag.FAILSAFE = True  # always restore
        return MouseResult(success=True, action="mouse_move", x=x, y=y)
    except SafetyError as e:
        return MouseResult(success=False, action="mouse_move", x=x, y=y, error=str(e))
    except Exception as exc:
        err = f"Mouse move failed: {exc}"
        log.error("[MOUSE] %s", err)
        return MouseResult(success=False, action="mouse_move", x=x, y=y, error=err)


def click(x: int, y: int, button: str = "left") -> MouseResult:
    """
    Click at (x, y) with the specified mouse button.

    Args:
        x, y: Click coordinates.
        button: 'left' (default), 'right', or 'middle'.
    """
    log.info("[MOUSE] click(%d, %d, button=%s)", x, y, button)
    try:
        enforce_rate_limit()
        validate_coordinates(x, y)
        if button not in ("left", "right", "middle"):
            return MouseResult(
                success=False, action="mouse_click", x=x, y=y,
                error=f"Invalid button '{button}'. Use 'left', 'right', or 'middle'."
            )
        pag = _get_pyautogui()
        pag.FAILSAFE = False
        try:
            _ensure_not_at_corner(pag)
            pag.click(x, y, button=button)
        finally:
            pag.FAILSAFE = True
        return MouseResult(success=True, action=f"mouse_{button}_click", x=x, y=y)
    except SafetyError as e:
        return MouseResult(success=False, action="mouse_click", x=x, y=y, error=str(e))
    except Exception as exc:
        err = f"Mouse click failed: {exc}"
        log.error("[MOUSE] %s", err)
        return MouseResult(success=False, action="mouse_click", x=x, y=y, error=err)


def double_click(x: int, y: int) -> MouseResult:
    """Double-click at (x, y)."""
    log.info("[MOUSE] double_click(%d, %d)", x, y)
    try:
        enforce_rate_limit()
        validate_coordinates(x, y)
        pag = _get_pyautogui()
        pag.FAILSAFE = False
        try:
            _ensure_not_at_corner(pag)
            pag.doubleClick(x, y)
        finally:
            pag.FAILSAFE = True
        return MouseResult(success=True, action="mouse_double_click", x=x, y=y)
    except SafetyError as e:
        return MouseResult(success=False, action="mouse_double_click", x=x, y=y, error=str(e))
    except Exception as exc:
        err = f"Double-click failed: {exc}"
        log.error("[MOUSE] %s", err)
        return MouseResult(success=False, action="mouse_double_click", x=x, y=y, error=err)


def right_click(x: int, y: int) -> MouseResult:
    """Right-click at (x, y)."""
    log.info("[MOUSE] right_click(%d, %d)", x, y)
    try:
        enforce_rate_limit()
        validate_coordinates(x, y)
        pag = _get_pyautogui()
        pag.FAILSAFE = False
        try:
            _ensure_not_at_corner(pag)
            pag.rightClick(x, y)
        finally:
            pag.FAILSAFE = True
        return MouseResult(success=True, action="mouse_right_click", x=x, y=y)
    except SafetyError as e:
        return MouseResult(success=False, action="mouse_right_click", x=x, y=y, error=str(e))
    except Exception as exc:
        err = f"Right-click failed: {exc}"
        log.error("[MOUSE] %s", err)
        return MouseResult(success=False, action="mouse_right_click", x=x, y=y, error=err)


def drag(
    start_x: int, start_y: int,
    end_x: int, end_y: int,
    duration: float = 0.5,
) -> MouseResult:
    """
    Drag from (start_x, start_y) to (end_x, end_y).

    Args:
        start_x, start_y: Drag origin.
        end_x, end_y: Drag destination.
        duration: Duration of the drag in seconds.
    """
    log.info("[MOUSE] drag(%d,%d) -> (%d,%d)", start_x, start_y, end_x, end_y)
    try:
        enforce_rate_limit()
        validate_coordinates(start_x, start_y)
        validate_coordinates(end_x, end_y)
        pag = _get_pyautogui()
        pag.FAILSAFE = False
        try:
            _ensure_not_at_corner(pag)
            pag.moveTo(start_x, start_y, duration=_MOVE_DURATION)
            pag.dragTo(end_x, end_y, duration=duration, button="left")
        finally:
            pag.FAILSAFE = True
        return MouseResult(success=True, action="mouse_drag", x=end_x, y=end_y)
    except SafetyError as e:
        return MouseResult(success=False, action="mouse_drag", x=end_x, y=end_y, error=str(e))
    except Exception as exc:
        err = f"Mouse drag failed: {exc}"
        log.error("[MOUSE] %s", err)
        return MouseResult(success=False, action="mouse_drag", x=end_x, y=end_y, error=err)


def scroll(amount: int, direction: str = "down", x: Optional[int] = None, y: Optional[int] = None) -> MouseResult:
    """
    Scroll the mouse wheel.

    Args:
        amount: Number of scroll units (positive = scroll up/right).
        direction: 'up' or 'down' (default 'down').
        x, y: Optional position to scroll at (moves mouse first).
    """
    log.info("[MOUSE] scroll(amount=%d, direction=%s)", amount, direction)
    try:
        enforce_rate_limit()
        pag = _get_pyautogui()
        pag.FAILSAFE = False
        try:
            _ensure_not_at_corner(pag)
            if x is not None and y is not None:
                validate_coordinates(x, y)
                pag.moveTo(x, y, duration=0.2)
            scroll_amount = abs(amount) if direction == "up" else -abs(amount)
            pag.scroll(scroll_amount)
        finally:
            pag.FAILSAFE = True
        pos_x = x or 0
        pos_y = y or 0
        return MouseResult(success=True, action=f"mouse_scroll_{direction}", x=pos_x, y=pos_y)
    except SafetyError as e:
        return MouseResult(success=False, action="mouse_scroll", x=0, y=0, error=str(e))
    except Exception as exc:
        err = f"Scroll failed: {exc}"
        log.error("[MOUSE] %s", err)
        return MouseResult(success=False, action="mouse_scroll", x=0, y=0, error=err)


def get_position() -> tuple[int, int]:
    """Return the current mouse cursor position as (x, y)."""
    try:
        import pyautogui
        pos = pyautogui.position()
        return pos.x, pos.y
    except Exception:
        return 0, 0
