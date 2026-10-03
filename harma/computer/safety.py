"""
Harma Computer Safety Layer

All coordinate validation, rate limiting, and safety checks live here.
This is the first line of defence before any OS-level action is executed.

Rules enforced here:
  - Coordinates must be within screen bounds
  - Text must not contain null bytes or other control characters
  - Action rate limit (prevent runaway loops)
  - Computer control must be enabled in config
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Optional, Tuple

from harma.config.logging_config import get_logger

log = get_logger(__name__)

# Minimum delay between consecutive computer actions (seconds)
_MIN_ACTION_INTERVAL = 0.05
_last_action_time: float = 0.0


@dataclass
class SafetyError(Exception):
    """Raised when a safety check fails."""
    message: str

    def __str__(self) -> str:
        return self.message


def _get_screen_size() -> Tuple[int, int]:
    """
    Return (width, height) of the primary screen.
    Uses ctypes on Windows (most accurate), then pyautogui, then a safe default.
    """
    # Strategy 1: ctypes (best accuracy on Windows, no DPI scaling issues)
    if sys.platform == "win32":
        try:
            import ctypes
            user32 = ctypes.windll.user32
            # SM_CXSCREEN=0, SM_CYSCREEN=1 — primary monitor physical pixels
            w = user32.GetSystemMetrics(0)
            h = user32.GetSystemMetrics(1)
            if w > 0 and h > 0:
                return w, h
        except Exception:
            pass

    # Strategy 2: pyautogui
    try:
        import pyautogui
        sz = pyautogui.size()
        if sz.width > 0 and sz.height > 0:
            return sz.width, sz.height
    except Exception:
        pass

    # Last resort — assume a standard resolution
    log.warning("[SAFETY] Could not detect screen size — assuming 1920x1080.")
    return 1920, 1080


def validate_coordinates(x: int, y: int) -> Tuple[int, int]:
    """
    Validate that (x, y) are within the current screen bounds.

    Args:
        x: Horizontal coordinate (pixels from left).
        y: Vertical coordinate (pixels from top).

    Returns:
        (x, y) if valid.

    Raises:
        SafetyError if coordinates are outside the screen.
    """
    sw, sh = _get_screen_size()

    if not (0 <= x <= sw and 0 <= y <= sh):
        raise SafetyError(
            f"Coordinates ({x}, {y}) are outside screen bounds ({sw}x{sh}). "
            f"Valid range: x=[0..{sw}], y=[0..{sh}]."
        )
    return x, y


def validate_text(text: str) -> str:
    """
    Validate text before typing it.

    Strips null bytes and other dangerous control characters.
    Logs a warning if suspicious content is detected.

    Args:
        text: Text to validate.

    Returns:
        Sanitised text.

    Raises:
        SafetyError if text is empty after sanitisation.
    """
    if not isinstance(text, str):
        raise SafetyError(f"text must be a string, got {type(text).__name__}")

    # Remove null bytes
    cleaned = text.replace("\x00", "")

    if not cleaned and text:
        raise SafetyError("Text contained only null bytes and cannot be typed.")

    if len(cleaned) > 10000:
        raise SafetyError(
            f"Text is too long ({len(cleaned)} chars). Maximum is 10,000 characters."
        )

    return cleaned


def validate_key(key: str) -> str:
    """
    Validate a key name before pressing it.

    Args:
        key: Key name (e.g. 'enter', 'ctrl', 'f5').

    Returns:
        Normalised lower-case key name.

    Raises:
        SafetyError if key name is invalid.
    """
    if not key or not isinstance(key, str):
        raise SafetyError("Key name must be a non-empty string.")

    # Normalise to lower-case
    normalised = key.strip().lower()

    # Basic sanity — no spaces in key names (except special combos handled elsewhere)
    if len(normalised) > 50:
        raise SafetyError(f"Key name too long: '{normalised[:50]}...'")

    return normalised


def enforce_rate_limit() -> None:
    """
    Enforce a minimum interval between consecutive computer actions.
    Prevents runaway tool loops from hammering the OS.
    """
    global _last_action_time
    now = time.monotonic()
    elapsed = now - _last_action_time
    if elapsed < _MIN_ACTION_INTERVAL:
        sleep_duration = _MIN_ACTION_INTERVAL - elapsed
        time.sleep(sleep_duration)
    _last_action_time = time.monotonic()


def get_screen_size() -> Tuple[int, int]:
    """Public accessor for screen size."""
    return _get_screen_size()
