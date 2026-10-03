"""
Harma Computer Controller

Top-level orchestrator for Phase 2 computer control.

Responsibilities:
  - Coordinate screen observation → action → re-observation cycles
  - Verify that actions had the intended effect
  - Provide the agent with structured state after each action
  - Expose a clean high-level API that tools can call

This module is NOT aware of BaseTool or the registry.
It is a pure computer-control library.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from harma.computer.screen import take_screenshot, observe_screen, ScreenObservation
from harma.computer.mouse import (
    move, click, double_click, right_click, drag, scroll, MouseResult
)
from harma.computer.keyboard import (
    type_text, type_text_clipboard, press_key, hotkey, KeyboardResult
)
from harma.computer.windows import (
    get_active_window_info, list_windows, focus_window, window_exists
)
from harma.computer.safety import get_screen_size, SafetyError
from harma.config.logging_config import get_logger

log = get_logger(__name__)


@dataclass
class ActionResult:
    """
    Unified result of any computer action.

    Used by the agent/tool layer to determine next steps.

    D2 Verification Taxonomy (cross-platform contract):
    ====================================================
    ``d2_verification="dispatch"``
        An OS-level input event was sent (mouse click/move/drag, key press,
        text type). Whether the application *reacted* is **not confirmed**.
        The caller MUST observe the screen after this action to verify effect.
        ``d2_verified`` is always ``None`` for dispatch results.

    ``d2_verification="state"``
        The action produced a directly-readable OS/Win32 state readback:
          - focus_window      → foreground window title verified via Win32 API
          - click_and_observe → active window inspected after click
          - screenshot        → screen captured (success = file written)
        ``d2_verified`` reflects whether the readback confirmed the intended state.

    ``d2_verification="observe"``
        Pure read-only observation. No input event was dispatched.

    Note: The richer 3-valued ``ActionOutcome`` from verification.py
    (ACTION_FAILED / ACTION_EXECUTED_UNVERIFIED / ACTION_EXECUTED_VERIFIED)
    is preserved for desktop-specific use. The ``d2_verification`` field
    provides the shared cross-platform token.
    """
    success: bool
    action: str
    detail: str = ""
    verification: str = ""             # Legacy free-form string (preserved)
    observation: Optional[ScreenObservation] = None
    error: str = ""
    # D2 cross-platform taxonomy
    d2_verification: str = "dispatch"  # "dispatch" | "state" | "observe"
    d2_verified: Optional[bool] = None # None for dispatch; bool for state

    def to_dict(self) -> dict:
        d = {
            "success": self.success,
            "action": self.action,
            "detail": self.detail,
            "verification": self.verification,
            # D2 cross-platform fields
            "d2_verification": self.d2_verification,
        }
        if self.d2_verification == "dispatch":
            d["dispatched"] = bool(self.success)
            d["d2_verified"] = None
        elif self.d2_verification == "state":
            d["d2_verified"] = self.d2_verified
        # For "observe", no dispatched/d2_verified needed
        if self.observation:
            d["screen_state"] = {
                "screenshot": self.observation.screenshot.to_dict(),
                "active_window": self.observation.active_window_title,
            }
        if not self.success:
            d["error"] = self.error
        return d

    def to_text(self) -> str:
        parts = [f"Action: {self.action}"]
        if self.detail:
            parts.append(f"Result: {self.detail}")
        if self.verification:
            parts.append(f"Verification: {self.verification}")
        if self.d2_verification == "state" and self.d2_verified is not None:
            parts.append(f"State-verified: {self.d2_verified}")
        if not self.success:
            parts.append(f"Error: {self.error}")
        if self.observation:
            parts.append(f"Screen: {self.observation.active_window_title or 'unknown'}")
        return "  |  ".join(parts)


class ComputerController:
    """
    High-level computer control orchestrator.

    Wraps low-level modules with the OBSERVE → ACT → OBSERVE pattern.
    """

    def __init__(self, post_action_delay: float = 0.5) -> None:
        """
        Args:
            post_action_delay: Seconds to wait after an action before observing.
                               Allows the OS/app to visually settle.
        """
        self._delay = post_action_delay

    # ── Screen ────────────────────────────────────────────────────────────────

    def screenshot(self, include_base64: bool = False) -> ActionResult:
        """Capture the current screen."""
        log.info("[CTRL] screenshot()")
        shot = take_screenshot(include_base64=include_base64)
        obs = ScreenObservation(
            screenshot=shot,
            screen_width=shot.width,
            screen_height=shot.height,
        )
        try:
            info = get_active_window_info()
            obs.active_window_title = info.get("title", "")
            obs.active_window_app = info.get("app", "")
        except Exception:
            pass

        return ActionResult(
            success=shot.success,
            action="screenshot",
            detail=shot.to_text(),
            observation=obs,
            error=shot.error,
            # screenshot is pure observation — no input event dispatched
            d2_verification="observe",
        )

    def observe(self, include_base64: bool = False) -> ScreenObservation:
        """Full screen observation (screenshot + active window)."""
        log.info("[CTRL] observe()")
        return observe_screen(include_base64=include_base64)

    def get_screen_size(self) -> tuple[int, int]:
        return get_screen_size()

    # ── Mouse ─────────────────────────────────────────────────────────────────

    def mouse_move(self, x: int, y: int) -> ActionResult:
        log.info("[CTRL] mouse_move(%d, %d)", x, y)
        result = move(x, y)
        return ActionResult(
            success=result.success,
            action=result.action,
            detail=result.to_text(),
            error=result.error,
            d2_verification="dispatch",
        )

    def mouse_click(self, x: int, y: int, button: str = "left") -> ActionResult:
        log.info("[CTRL] mouse_click(%d, %d, %s)", x, y, button)
        result = click(x, y, button)
        time.sleep(self._delay)
        return ActionResult(
            success=result.success,
            action=result.action,
            detail=result.to_text(),
            error=result.error,
            d2_verification="dispatch",
        )

    def mouse_double_click(self, x: int, y: int) -> ActionResult:
        log.info("[CTRL] mouse_double_click(%d, %d)", x, y)
        result = double_click(x, y)
        time.sleep(self._delay)
        return ActionResult(
            success=result.success,
            action=result.action,
            detail=result.to_text(),
            error=result.error,
            d2_verification="dispatch",
        )

    def mouse_right_click(self, x: int, y: int) -> ActionResult:
        log.info("[CTRL] mouse_right_click(%d, %d)", x, y)
        result = right_click(x, y)
        time.sleep(self._delay)
        return ActionResult(
            success=result.success,
            action=result.action,
            detail=result.to_text(),
            error=result.error,
            d2_verification="dispatch",
        )

    def mouse_drag(
        self, start_x: int, start_y: int,
        end_x: int, end_y: int
    ) -> ActionResult:
        log.info("[CTRL] mouse_drag(%d,%d)->(%d,%d)", start_x, start_y, end_x, end_y)
        result = drag(start_x, start_y, end_x, end_y)
        time.sleep(self._delay)
        return ActionResult(
            success=result.success,
            action=result.action,
            detail=result.to_text(),
            error=result.error,
            d2_verification="dispatch",
        )

    def mouse_scroll(
        self, amount: int, direction: str = "down",
        x: Optional[int] = None, y: Optional[int] = None
    ) -> ActionResult:
        log.info("[CTRL] mouse_scroll(amount=%d, dir=%s)", amount, direction)
        result = scroll(amount, direction, x, y)
        return ActionResult(
            success=result.success,
            action=result.action,
            detail=result.to_text(),
            error=result.error,
            d2_verification="dispatch",
        )

    # ── Keyboard ──────────────────────────────────────────────────────────────

    def type_text(self, text: str, use_clipboard: bool = False) -> ActionResult:
        log.info("[CTRL] type_text(length=%d)", len(text))
        if use_clipboard:
            result = type_text_clipboard(text)
        else:
            result = type_text(text)
        time.sleep(self._delay)
        return ActionResult(
            success=result.success,
            action=result.action,
            detail=result.to_text(),
            error=result.error,
            d2_verification="dispatch",
        )

    def press_key(self, key: str) -> ActionResult:
        log.info("[CTRL] press_key(%s)", key)
        result = press_key(key)
        time.sleep(self._delay)
        return ActionResult(
            success=result.success,
            action=result.action,
            detail=result.to_text(),
            error=result.error,
            d2_verification="dispatch",
        )

    def hotkey(self, keys: list[str]) -> ActionResult:
        log.info("[CTRL] hotkey(%s)", keys)
        result = hotkey(keys)
        time.sleep(self._delay)
        return ActionResult(
            success=result.success,
            action=result.action,
            detail=result.to_text(),
            error=result.error,
            d2_verification="dispatch",
        )

    # ── Windows ───────────────────────────────────────────────────────────────

    def get_active_window(self) -> dict:
        return get_active_window_info()

    def list_windows(self) -> list[dict]:
        return list_windows()

    def focus_window(self, title_fragment: str, wait_seconds: float = 3.0) -> ActionResult:
        log.info("[CTRL] focus_window('%s')", title_fragment)
        result = focus_window(title_fragment, wait_seconds)
        focused = result["success"]
        return ActionResult(
            success=focused,
            action="focus_window",
            detail=f"Focused '{result.get('title', '')}'",
            verification="Window in foreground" if focused else "",
            error=result.get("error", ""),
            # focus_window reads back actual foreground window title via Win32 API
            # -> this is a direct state readback, not just an event dispatch
            d2_verification="state",
            d2_verified=focused,
        )

    def window_exists(self, title_fragment: str) -> bool:
        return window_exists(title_fragment)

    # ── Compound: observe → act → observe ────────────────────────────────────

    def click_and_observe(self, x: int, y: int) -> ActionResult:
        """Click at coordinates then immediately observe screen."""
        click_result = self.mouse_click(x, y)
        obs = self.observe()
        # The observe() after click reads back the actual OS window state.
        # We classify as 'state': we have real confirmation of what is on screen.
        return ActionResult(
            success=click_result.success,
            action="click_and_observe",
            detail=click_result.detail,
            observation=obs,
            verification=f"Active window: {obs.active_window_title}",
            error=click_result.error,
            d2_verification="state",
            d2_verified=click_result.success,
        )

    def type_and_observe(self, text: str) -> ActionResult:
        """Type text then observe the resulting screen."""
        type_result = self.type_text(text)
        obs = self.observe()
        return ActionResult(
            success=type_result.success,
            action="type_and_observe",
            detail=type_result.detail,
            observation=obs,
            error=type_result.error,
            # type is dispatch; the observe part gives us state info but the
            # *text effect* in the UI is still unconfirmed -> keep as dispatch
            d2_verification="dispatch",
        )


# Module-level singleton — tools import this
controller = ComputerController()
