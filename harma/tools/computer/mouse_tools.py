"""
Mouse Tools — Phase 2

Exposes mouse control capabilities as Harma tools.

Tools:
  mouse_move          — Move cursor (SAFE)
  mouse_click         — Left/right/middle click (SENSITIVE)
  mouse_double_click  — Double-click (SENSITIVE)
  mouse_right_click   — Right-click (SENSITIVE)
  mouse_drag          — Drag from point to point (SENSITIVE)
  mouse_scroll        — Scroll the mouse wheel (SAFE)
"""

from __future__ import annotations

from typing import Any

from harma.tools.base import BaseTool, PermissionLevel, ToolResult
from harma.config.logging_config import get_logger

log = get_logger(__name__)


class MouseMoveTool(BaseTool):
    name = "mouse_move"
    description = (
        "Moves the mouse cursor to the specified screen coordinates without clicking. "
        "Useful for hovering over UI elements before a click."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "Horizontal screen coordinate (pixels from left)."},
            "y": {"type": "integer", "description": "Vertical screen coordinate (pixels from top)."},
        },
        "required": ["x", "y"],
    }

    async def execute(self, x: int, y: int, **kwargs: Any) -> ToolResult:
        from harma.computer.mouse import move
        result = move(x, y)
        return ToolResult(
            success=result.success,
            output=result.to_text(),
            data=result.to_dict(),
            error=result.error,
        )


class MouseClickTool(BaseTool):
    name = "mouse_click"
    description = (
        "Clicks at the specified screen coordinates. "
        "Use this to click buttons, links, form fields, or any UI element. "
        "Optionally specify 'right' or 'middle' for different button clicks."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "Horizontal screen coordinate."},
            "y": {"type": "integer", "description": "Vertical screen coordinate."},
            "button": {
                "type": "string",
                "enum": ["left", "right", "middle"],
                "description": "Mouse button to use (default: 'left').",
            },
        },
        "required": ["x", "y"],
    }

    async def execute(self, x: int, y: int, button: str = "left", **kwargs: Any) -> ToolResult:
        from harma.computer.mouse import click
        result = click(x, y, button)
        return ToolResult(
            success=result.success,
            output=result.to_text(),
            data=result.to_dict(),
            error=result.error,
        )


class MouseDoubleClickTool(BaseTool):
    name = "mouse_double_click"
    description = (
        "Double-clicks at the specified screen coordinates. "
        "Use for opening files/folders or selecting words in text fields."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "Horizontal screen coordinate."},
            "y": {"type": "integer", "description": "Vertical screen coordinate."},
        },
        "required": ["x", "y"],
    }

    async def execute(self, x: int, y: int, **kwargs: Any) -> ToolResult:
        from harma.computer.mouse import double_click
        result = double_click(x, y)
        return ToolResult(
            success=result.success,
            output=result.to_text(),
            data=result.to_dict(),
            error=result.error,
        )


class MouseRightClickTool(BaseTool):
    name = "mouse_right_click"
    description = (
        "Right-clicks at the specified screen coordinates to open a context menu."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "Horizontal screen coordinate."},
            "y": {"type": "integer", "description": "Vertical screen coordinate."},
        },
        "required": ["x", "y"],
    }

    async def execute(self, x: int, y: int, **kwargs: Any) -> ToolResult:
        from harma.computer.mouse import right_click
        result = right_click(x, y)
        return ToolResult(
            success=result.success,
            output=result.to_text(),
            data=result.to_dict(),
            error=result.error,
        )


class MouseDragTool(BaseTool):
    name = "mouse_drag"
    description = (
        "Drags the mouse from one screen position to another. "
        "Use for drag-and-drop operations, selecting text ranges, or moving windows."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "start_x": {"type": "integer", "description": "Starting X coordinate."},
            "start_y": {"type": "integer", "description": "Starting Y coordinate."},
            "end_x":   {"type": "integer", "description": "Ending X coordinate."},
            "end_y":   {"type": "integer", "description": "Ending Y coordinate."},
        },
        "required": ["start_x", "start_y", "end_x", "end_y"],
    }

    async def execute(
        self,
        start_x: int, start_y: int,
        end_x: int, end_y: int,
        **kwargs: Any,
    ) -> ToolResult:
        from harma.computer.mouse import drag
        result = drag(start_x, start_y, end_x, end_y)
        return ToolResult(
            success=result.success,
            output=result.to_text(),
            data=result.to_dict(),
            error=result.error,
        )


class MouseScrollTool(BaseTool):
    name = "mouse_scroll"
    description = (
        "Scrolls the mouse wheel up or down. "
        "Use this to scroll through lists, web pages, or documents."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "amount": {
                "type": "integer",
                "description": "Number of scroll steps (1-20 typical).",
            },
            "direction": {
                "type": "string",
                "enum": ["up", "down"],
                "description": "Scroll direction (default: 'down').",
            },
            "x": {"type": "integer", "description": "Optional X coordinate to scroll at."},
            "y": {"type": "integer", "description": "Optional Y coordinate to scroll at."},
        },
        "required": ["amount"],
    }

    async def execute(
        self,
        amount: int,
        direction: str = "down",
        x: int | None = None,
        y: int | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        from harma.computer.mouse import scroll
        result = scroll(amount, direction, x, y)
        return ToolResult(
            success=result.success,
            output=result.to_text(),
            data=result.to_dict(),
            error=result.error,
        )
