"""
Browser Tab Tools — Phase 3

Tab (page) management tools.

Tools:
  list_browser_tabs   — Show all open tabs (SAFE)
  new_browser_tab     — Open a new tab (SAFE)
  switch_browser_tab  — Switch to a tab by index (SAFE)
  close_browser_tab   — Close a tab (SAFE)
"""

from __future__ import annotations

from typing import Any

from harma.tools.base import BaseTool, PermissionLevel, ToolResult
from harma.config.logging_config import get_logger

log = get_logger(__name__)


def _get_ctrl():
    from harma.browser.controller import get_browser_controller
    return get_browser_controller()


class ListBrowserTabsTool(BaseTool):
    name = "list_browser_tabs"
    description = (
        "Lists all currently open browser tabs with their index, URL, and title. "
        "Use to understand the current tab state before switching tabs."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> ToolResult:
        ctrl = _get_ctrl()
        if not ctrl.is_open:
            return ToolResult(success=False, output="", error="Browser is not open.")
        tabs = ctrl.list_tabs()
        if not tabs:
            return ToolResult(success=True, output="No tabs open.", data={"tabs": []})
        lines = []
        for t in tabs:
            marker = "▶" if t.is_active else " "
            lines.append(f"  {marker} [{t.index}] {t.url}")
        return ToolResult(
            success=True,
            output="Open tabs:\n" + "\n".join(lines),
            data={"tabs": [t.__dict__ for t in tabs]},
        )


class NewBrowserTabTool(BaseTool):
    name = "new_browser_tab"
    description = "Opens a new browser tab, optionally navigating to a URL."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Optional URL to open in the new tab.",
            }
        },
        "required": [],
    }

    async def execute(self, url: str = "", **kwargs: Any) -> ToolResult:
        ctrl = _get_ctrl()
        if not ctrl.is_open:
            return ToolResult(success=False, output="", error="Browser is not open.")
        result = await ctrl.new_tab(url)
        return ToolResult(
            success=result.success, output=result.to_text(),
            data=result.to_dict(), error=result.error,
        )


class SwitchBrowserTabTool(BaseTool):
    name = "switch_browser_tab"
    description = (
        "Switches to a specific browser tab by its index number. "
        "Use list_browser_tabs to see available tabs and their indices."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "index": {
                "type": "integer",
                "description": "Zero-based index of the tab to switch to.",
            }
        },
        "required": ["index"],
    }

    async def execute(self, index: int, **kwargs: Any) -> ToolResult:
        ctrl = _get_ctrl()
        if not ctrl.is_open:
            return ToolResult(success=False, output="", error="Browser is not open.")
        result = await ctrl.switch_tab(index)
        return ToolResult(
            success=result.success, output=result.to_text(),
            data=result.to_dict(), error=result.error,
        )


class CloseBrowserTabTool(BaseTool):
    name = "close_browser_tab"
    description = (
        "Closes a browser tab by index. "
        "If no index is given, closes the currently active tab."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "index": {
                "type": "integer",
                "description": "Index of the tab to close (default: active tab).",
            }
        },
        "required": [],
    }

    async def execute(self, index: int = None, **kwargs: Any) -> ToolResult:
        ctrl = _get_ctrl()
        if not ctrl.is_open:
            return ToolResult(success=False, output="", error="Browser is not open.")
        result = await ctrl.close_tab(index)
        return ToolResult(
            success=result.success, output=result.to_text(),
            data=result.to_dict(), error=result.error,
        )
