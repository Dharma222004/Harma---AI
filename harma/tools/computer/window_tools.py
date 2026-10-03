"""
Window Tools — Phase 2

Exposes window management as Harma tools.

Tools:
  get_active_window   — Get current foreground window info (SAFE)
  list_open_windows   — List all visible windows (SAFE)
  focus_application   — Focus/bring a window to front (SAFE)
  find_ui_element     — Find a UI element by text description (SAFE)
  click_element       — Find + click a UI element by description (SENSITIVE)
"""

from __future__ import annotations

import json
from typing import Any

from harma.tools.base import BaseTool, PermissionLevel, ToolResult
from harma.config.logging_config import get_logger

log = get_logger(__name__)


class GetActiveWindowTool(BaseTool):
    name = "get_active_window"
    description = (
        "Returns information about the currently active/focused window. "
        "Use this to verify which application is in the foreground."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        from harma.computer.windows import get_active_window_info
        info = get_active_window_info()
        title = info.get("title", "")
        app = info.get("app", "")
        lines = [f"Active window: '{title}'"]
        if app:
            lines.append(f"Application: {app}")
        geo = info.get("geometry", {})
        if geo:
            lines.append(
                f"Position: ({geo.get('left', 0)}, {geo.get('top', 0)})  "
                f"Size: {geo.get('width', 0)}x{geo.get('height', 0)}"
            )
        return ToolResult(
            success=True,
            output="\n".join(lines),
            data=info,
        )


class ListOpenWindowsTool(BaseTool):
    name = "list_open_windows"
    description = (
        "Lists all currently visible windows on screen. "
        "Use this to find which applications are open and their titles."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        from harma.computer.windows import list_windows
        windows = list_windows()
        if not windows:
            return ToolResult(
                success=True,
                output="No visible windows found.",
                data={"windows": []},
            )
        lines = [f"Open windows ({len(windows)}):"]
        for i, w in enumerate(windows[:20], 1):  # cap at 20 for readability
            lines.append(f"  {i}. {w.get('title', '(no title)')}")
        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"windows": windows[:20]},
        )


class FocusApplicationTool(BaseTool):
    name = "focus_application"
    description = (
        "Brings an application window to the foreground by matching its title. "
        "Use this after opening an application to ensure it's in focus before typing. "
        "Provide a fragment of the window title (e.g. 'Notepad', 'Chrome')."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "window_title": {
                "type": "string",
                "description": "Part of the window title to match (case-insensitive).",
            },
            "wait_seconds": {
                "type": "number",
                "description": "Seconds to wait for the window to appear (default: 3.0).",
            },
        },
        "required": ["window_title"],
    }

    async def execute(
        self,
        window_title: str,
        wait_seconds: float = 3.0,
        **kwargs: Any,
    ) -> ToolResult:
        from harma.computer.windows import focus_window
        result = focus_window(window_title, wait_seconds)
        if result["success"]:
            return ToolResult(
                success=True,
                output=f"Focused window: '{result['title']}'",
                data=result,
            )
        return ToolResult(
            success=False,
            output="",
            error=result.get("error", f"Could not find window '{window_title}'."),
        )


class FindUIElementTool(BaseTool):
    name = "find_ui_element"
    description = (
        "Finds a UI element on screen by its text description. "
        "Returns the screen coordinates of the element if found. "
        "Use the coordinates with mouse_click to interact with the element."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Text description of the element to find (e.g. 'address bar', 'OK button', 'search box').",
            },
        },
        "required": ["description"],
    }

    async def execute(self, description: str, **kwargs: Any) -> ToolResult:
        from harma.computer.ui_detection import find_text_on_screen
        element = find_text_on_screen(description)
        if element.found:
            return ToolResult(
                success=True,
                output=element.to_text(),
                data=element.to_dict(),
            )
        return ToolResult(
            success=False,
            output="",
            error=element.error or f"Could not find '{description}' on screen.",
        )


class ClickElementTool(BaseTool):
    name = "click_element"
    description = (
        "Finds a UI element by text description and clicks on it. "
        "Combines find_ui_element + mouse_click in one step. "
        "Use this to click buttons, menu items, or any named UI element."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Text description of the element to click.",
            },
            "double_click": {
                "type": "boolean",
                "description": "If true, double-click the element (default: false).",
            },
        },
        "required": ["description"],
    }

    async def execute(
        self,
        description: str,
        double_click: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        from harma.computer.ui_detection import find_text_on_screen
        from harma.computer.mouse import click as mouse_click, double_click as mouse_double_click

        element = find_text_on_screen(description)
        if not element.found:
            return ToolResult(
                success=False,
                output="",
                error=element.error or f"Could not find '{description}' on screen.",
            )

        if double_click:
            mouse_result = mouse_double_click(element.x, element.y)
        else:
            mouse_result = mouse_click(element.x, element.y)

        return ToolResult(
            success=mouse_result.success,
            output=f"Clicked '{description}' at ({element.x}, {element.y})",
            data={
                "element": element.to_dict(),
                "click": mouse_result.to_dict(),
            },
            error=mouse_result.error,
        )
