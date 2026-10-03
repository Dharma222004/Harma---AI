"""
Harma Screen Module

Low-level screen capture and observation.
Uses PIL/Pillow + pyautogui under the hood.

Returns structured data — NOT raw binary in text responses.
Screenshots are saved to a temp directory and referenced by path.
"""

from __future__ import annotations

import base64
import io
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

from harma.computer.safety import get_screen_size, SafetyError
from harma.config.logging_config import get_logger

log = get_logger(__name__)

# Directory where screenshots are saved during the session
_SCREENSHOT_DIR = Path(tempfile.gettempdir()) / "harma_screenshots"


@dataclass
class ScreenshotResult:
    """
    Result of a screenshot operation.

    image_path  — absolute path to the saved PNG file.
    width       — screen width in pixels.
    height      — screen height in pixels.
    timestamp   — Unix timestamp of capture.
    base64      — Optional base64-encoded PNG (for LLM vision APIs).
    error       — Non-empty if capture failed.
    """
    success: bool
    image_path: str = ""
    width: int = 0
    height: int = 0
    timestamp: float = field(default_factory=time.time)
    base64_data: Optional[str] = None
    error: str = ""

    def to_dict(self) -> dict:
        d = {
            "success": self.success,
            "width": self.width,
            "height": self.height,
            "timestamp": self.timestamp,
            "image_path": self.image_path,
        }
        if not self.success:
            d["error"] = self.error
        return d

    def to_text(self) -> str:
        if not self.success:
            return f"Screenshot failed: {self.error}"
        return (
            f"Screenshot captured: {self.width}x{self.height}px  "
            f"saved to: {self.image_path}"
        )


@dataclass
class ScreenObservation:
    """
    A complete observation of the current screen state.

    Used by the agent's OBSERVE step.
    """
    screenshot: ScreenshotResult
    active_window_title: str = ""
    active_window_app: str = ""
    screen_width: int = 0
    screen_height: int = 0

    def to_text(self) -> str:
        lines = [self.screenshot.to_text()]
        if self.active_window_title:
            lines.append(f"Active window: {self.active_window_title}")
        if self.active_window_app:
            lines.append(f"Active app: {self.active_window_app}")
        return "\n".join(lines)


def _ensure_screenshot_dir() -> Path:
    _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return _SCREENSHOT_DIR


def _powershell_screenshot():
    """
    Capture the screen using PowerShell's System.Drawing API.

    More reliable than PIL.ImageGrab when running from a subprocess context
    (e.g. pytest, non-interactive shells) on Windows.

    Returns:
        PIL.Image if successful, or raises on failure.
    """
    import subprocess
    import tempfile
    from pathlib import Path as _Path
    from PIL import Image

    ps_script = _Path(__file__).parent / "screenshot_helper.ps1"
    if not ps_script.exists():
        raise FileNotFoundError(f"screenshot_helper.ps1 not found at {ps_script}")

    tmp_path = _Path(tempfile.gettempdir()) / f"harma_ps_{int(time.time() * 1000)}.png"

    result = subprocess.run(
        [
            "powershell", "-ExecutionPolicy", "Bypass",
            "-File", str(ps_script),
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )

    if tmp_path.exists() and tmp_path.stat().st_size > 0:
        img = Image.open(str(tmp_path))
        img = img.copy()  # load fully into memory so we can delete the file
        try:
            tmp_path.unlink()
        except Exception:
            pass
        log.debug("[SCREEN] PowerShell screenshot OK: %s", img.size)
        return img

    # If file wasn't created, raise with stderr info
    raise RuntimeError(
        f"PowerShell screenshot failed (rc={result.returncode}): "
        f"{result.stderr.strip()[:200]}"
    )


def take_screenshot(
    include_base64: bool = False,
    region: Optional[Tuple[int, int, int, int]] = None,
) -> ScreenshotResult:
    """
    Capture the current screen.

    Tries PIL.ImageGrab first (most reliable on Windows), then pyautogui.

    Args:
        include_base64: If True, encode the image as base64 for LLM vision APIs.
        region: Optional (left, top, width, height) to capture a region.
                On PIL.ImageGrab, region is (left, top, right, bottom).

    Returns:
        ScreenshotResult with path to saved PNG.
    """
    log.info("[SCREEN] Taking screenshot  region=%s", region)

    img = None
    error_msgs = []

    # ── Strategy 1: PIL.ImageGrab (Windows primary) ───────────────────────────
    try:
        from PIL import ImageGrab, Image
        if region:
            left, top, width, height = region
            bbox = (left, top, left + width, top + height)
            img = ImageGrab.grab(bbox=bbox, all_screens=True)
        else:
            img = ImageGrab.grab(all_screens=True)
    except Exception as exc:
        error_msgs.append(f"ImageGrab: {exc}")
        log.debug("[SCREEN] ImageGrab failed: %s", exc)

    # ── Strategy 2: pyautogui ─────────────────────────────────────────────────
    if img is None:
        try:
            import pyautogui
            from PIL import Image
            if region:
                img = pyautogui.screenshot(region=region)
            else:
                img = pyautogui.screenshot()
        except Exception as exc:
            error_msgs.append(f"pyautogui: {exc}")
            log.debug("[SCREEN] pyautogui screenshot failed: %s", exc)

    # ── Strategy 3: PowerShell CopyFromScreen ────────────────────────────────
    if img is None:
        try:
            img = _powershell_screenshot()
        except Exception as exc:
            error_msgs.append(f"PowerShell: {exc}")
            log.debug("[SCREEN] PowerShell screenshot failed: %s", exc)

    if img is None:
        err = "Screenshot failed: " + " | ".join(error_msgs)
        log.error("[SCREEN] %s", err)
        return ScreenshotResult(success=False, error=err)

    try:
        w, h = img.size
        ts = time.time()
        filename = f"harma_{int(ts * 1000)}.png"
        save_dir = _ensure_screenshot_dir()
        save_path = save_dir / filename
        img.save(str(save_path), "PNG")

        b64: Optional[str] = None
        if include_base64:
            buf = io.BytesIO()
            img.save(buf, "PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        log.info("[SCREEN] Screenshot saved: %s (%dx%d)", save_path, w, h)
        return ScreenshotResult(
            success=True,
            image_path=str(save_path),
            width=w,
            height=h,
            timestamp=ts,
            base64_data=b64,
        )
    except Exception as exc:
        err = f"Failed to save screenshot: {exc}"
        log.error("[SCREEN] %s", err)
        return ScreenshotResult(success=False, error=err)


def get_screen_dimensions() -> Tuple[int, int]:
    """Return (width, height) of the primary screen."""
    return get_screen_size()


def observe_screen(include_base64: bool = False) -> ScreenObservation:
    """
    Perform a full screen observation: screenshot + active window info.

    This is the OBSERVE step in the agent's OBSERVE → ACT → OBSERVE cycle.

    Args:
        include_base64: Include base64 image for LLM vision (Phase 3+).

    Returns:
        ScreenObservation with screenshot + window context.
    """
    log.info("[SCREEN] Observing screen state...")
    screenshot = take_screenshot(include_base64=include_base64)
    w, h = get_screen_size()

    active_title = ""
    active_app = ""
    try:
        from harma.computer.windows import get_active_window_info
        info = get_active_window_info()
        active_title = info.get("title", "")
        active_app = info.get("app", "")
    except Exception:
        pass

    return ScreenObservation(
        screenshot=screenshot,
        active_window_title=active_title,
        active_window_app=active_app,
        screen_width=w,
        screen_height=h,
    )
