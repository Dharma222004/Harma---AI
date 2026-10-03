"""
Screen Tools — Phase 2

Exposes screen observation and screenshot capabilities as Harma tools.

Tools:
  take_screenshot   — Capture the screen (SAFE)
  observe_screen    — Full screen state (screenshot + active window) (SAFE)
  get_screen_size   — Return screen dimensions (SAFE)
"""

from __future__ import annotations

import json
from typing import Any

from harma.tools.base import BaseTool, PermissionLevel, ToolResult
from harma.config.logging_config import get_logger

log = get_logger(__name__)


class TakeScreenshotTool(BaseTool):
    """Take a screenshot of the current screen."""

    name = "take_screenshot"
    description = (
        "Captures the current screen and saves it as a PNG file. "
        "Returns the file path and screen dimensions. "
        "Use this to observe the current screen state before or after actions."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "region": {
                "type": "object",
                "description": "Optional screen region to capture. Leave empty for full screen.",
                "properties": {
                    "left": {"type": "integer"},
                    "top": {"type": "integer"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                },
            }
        },
        "required": [],
    }

    async def execute(self, region: dict | None = None, **kwargs: Any) -> ToolResult:
        from harma.computer.screen import take_screenshot

        region_tuple = None
        if region:
            try:
                region_tuple = (
                    region["left"], region["top"],
                    region["width"], region["height"]
                )
            except KeyError:
                return ToolResult(
                    success=False, output="",
                    error="region must have: left, top, width, height"
                )

        result = take_screenshot(region=region_tuple)

        if result.success:
            return ToolResult(
                success=True,
                output=result.to_text(),
                data=result.to_dict(),
            )
        return ToolResult(
            success=False,
            output="",
            error=result.error,
        )


class ObserveScreenTool(BaseTool):
    """Observe the current screen state including active window information."""

    name = "observe_screen"
    description = (
        "Captures the screen and returns the current state: "
        "screenshot path, dimensions, and active window information. "
        "Use this after any action to verify what happened on screen."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        from harma.computer.screen import observe_screen
        from harma.computer.windows import get_active_window_info

        obs = observe_screen()

        # Always read foreground window (OS-level, cheap, reliable)
        active_title = obs.active_window_title
        active_app = obs.active_window_app
        try:
            fg_info = get_active_window_info()
            active_title = fg_info.get("title", active_title)
            active_app = fg_info.get("app", active_app)
        except Exception:
            pass

        lines = []
        if obs.screenshot.success:
            lines.append(f"Screenshot saved: {obs.screenshot.image_path}")
            lines.append(f"Screen size: {obs.screen_width}x{obs.screen_height}")
        else:
            lines.append(f"Screenshot failed: {obs.screenshot.error}")

        lines.append(f"Active window: {active_title or '(none)'}")
        lines.append(f"Active app process: {active_app or '(unknown)'}")

        # Verification guidance for the LLM
        if active_title:
            lines.append(
                f"OBSERVATION: Foreground window is '{active_title}'. "
                "Use this to confirm the expected application is in focus before "
                "reporting task completion."
            )

        return ToolResult(
            success=obs.screenshot.success,
            output="\n".join(lines),
            data={
                "screenshot": obs.screenshot.to_dict(),
                "active_window": active_title,
                "active_app": active_app,
                "screen_size": {
                    "width": obs.screen_width,
                    "height": obs.screen_height,
                },
                "observation_note": (
                    f"Foreground window is '{active_title}'. "
                    "Verify this matches the expected application before claiming task complete."
                ),
            },
        )


class GetScreenSizeTool(BaseTool):
    """Get the screen dimensions."""

    name = "get_screen_size"
    description = (
        "Returns the current screen width and height in pixels. "
        "Use before mouse operations to validate coordinate ranges."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        from harma.computer.safety import get_screen_size

        w, h = get_screen_size()
        return ToolResult(
            success=True,
            output=f"Screen size: {w}x{h} pixels",
            data={"width": w, "height": h},
        )
