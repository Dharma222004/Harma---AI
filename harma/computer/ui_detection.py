"""
Harma UI Element Detection

Pluggable interface for finding UI elements on screen.

Detection strategies (in priority order):
  1. Windows Accessibility API (pywinauto / win32 UIA)  — most reliable
  2. Image template matching (pyautogui.locateOnScreen)  — app-agnostic
  3. OCR (pytesseract)                                   — text-based fallback
  4. Vision model (Phase 3+)                             — LLM vision

This module is structured so new strategies can be added without
changing the caller interface (find_element / find_text_on_screen).
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

from harma.config.logging_config import get_logger

log = get_logger(__name__)


@dataclass
class UIElement:
    """
    Represents a located UI element.

    All coordinates are in screen pixels.
    """
    found: bool
    x: int = 0              # centre X
    y: int = 0              # centre Y
    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0
    label: str = ""         # human-readable description
    strategy: str = ""      # detection method used
    confidence: float = 1.0
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "found": self.found,
            "x": self.x, "y": self.y,
            "left": self.left, "top": self.top,
            "width": self.width, "height": self.height,
            "label": self.label,
            "strategy": self.strategy,
            "confidence": self.confidence,
        }

    def to_text(self) -> str:
        if not self.found:
            return f"Element not found: {self.error or self.label}"
        return (
            f"Found '{self.label}' at ({self.x}, {self.y}) "
            f"[{self.width}x{self.height}] via {self.strategy}"
        )


def find_text_on_screen(
    text: str,
    region: Optional[Tuple[int, int, int, int]] = None,
    confidence: float = 0.8,
) -> UIElement:
    """
    Find text on screen using image-based OCR via pyautogui.locateOnScreen.

    Since we can't do full OCR without tesseract, this version uses
    pyautogui's image search on the actual window titles / taskbar.

    For pure text detection, falls back to win32 accessibility search on Windows.

    Args:
        text: The text to find on screen.
        region: Optional (left, top, width, height) search region.
        confidence: Minimum confidence threshold (0.0–1.0).

    Returns:
        UIElement with coordinates if found, else found=False.
    """
    log.info("[UI] find_text_on_screen('%s')", text)

    # Strategy 1: Windows accessibility tree
    if sys.platform == "win32":
        result = _find_by_accessibility(text)
        if result.found:
            return result

    # Strategy 2: pyautogui screen text search (limited without OCR)
    # Falls back gracefully — do not crash if not available
    result = _find_by_window_title(text)
    if result.found:
        return result

    return UIElement(
        found=False,
        label=text,
        strategy="none",
        error=f"Could not locate '{text}' on screen.",
    )


def _find_by_accessibility(query: str) -> UIElement:
    """
    Search the Windows Accessibility (UIA) tree for an element matching query.
    Uses pywinauto if available, falls back to win32com UIA.
    """
    try:
        import pywinauto
        from pywinauto import Desktop

        desktop = Desktop(backend="uia")
        # Find element by name or auto_id
        try:
            element = desktop.window(title_re=f".*{query}.*")
            rect = element.rectangle()
            cx = (rect.left + rect.right) // 2
            cy = (rect.top + rect.bottom) // 2
            log.info("[UI] Found via accessibility: '%s' at (%d,%d)", query, cx, cy)
            return UIElement(
                found=True,
                x=cx, y=cy,
                left=rect.left, top=rect.top,
                width=rect.right - rect.left,
                height=rect.bottom - rect.top,
                label=query,
                strategy="accessibility_uia",
            )
        except Exception:
            pass
    except ImportError:
        pass

    return UIElement(found=False, label=query, strategy="accessibility_uia")


def _find_by_window_title(query: str) -> UIElement:
    """
    Find a window whose title matches query, return its position.
    This is a pragmatic fallback when full UIA search isn't available.
    """
    from harma.computer.windows import list_windows

    fragment = query.lower()
    windows = list_windows()
    for win in windows:
        if fragment in win.get("title", "").lower():
            geo = win.get("geometry", {})
            if geo.get("width", 0) > 0:
                cx = geo["left"] + geo["width"] // 2
                cy = geo["top"] + geo["height"] // 2
                log.info("[UI] Matched window title '%s'", win["title"])
                return UIElement(
                    found=True,
                    x=cx, y=cy,
                    left=geo["left"], top=geo["top"],
                    width=geo["width"], height=geo["height"],
                    label=win["title"],
                    strategy="window_title_match",
                )
    return UIElement(found=False, label=query, strategy="window_title_match")


def find_image_on_screen(
    image_path: str,
    confidence: float = 0.8,
    region: Optional[Tuple[int, int, int, int]] = None,
) -> UIElement:
    """
    Locate an image template on the screen using pyautogui.

    Args:
        image_path: Path to the template PNG/JPEG image.
        confidence: Minimum match confidence (requires opencv).
        region: Optional search region (left, top, width, height).

    Returns:
        UIElement with centre coordinates if found.
    """
    log.info("[UI] find_image_on_screen('%s')", image_path)

    if not Path(image_path).exists():
        return UIElement(
            found=False,
            label=image_path,
            strategy="image_match",
            error=f"Template image not found: {image_path}",
        )

    try:
        import pyautogui
        loc = pyautogui.locateOnScreen(
            image_path,
            confidence=confidence,
            region=region,
        )
        if loc:
            cx = loc.left + loc.width // 2
            cy = loc.top + loc.height // 2
            log.info("[UI] Image found at (%d,%d)", cx, cy)
            return UIElement(
                found=True,
                x=cx, y=cy,
                left=loc.left, top=loc.top,
                width=loc.width, height=loc.height,
                label=image_path,
                strategy="image_match",
                confidence=confidence,
            )
    except Exception as exc:
        log.debug("[UI] Image match error: %s", exc)

    return UIElement(
        found=False,
        label=image_path,
        strategy="image_match",
        error=f"Image template not found on screen.",
    )
