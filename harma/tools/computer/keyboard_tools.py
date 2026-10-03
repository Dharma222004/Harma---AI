"""
Keyboard Tools — Phase 2

Exposes keyboard control as Harma tools.

Tools:
  type_text   — Type a string of text (SENSITIVE)
  press_key   — Press a single key (SENSITIVE)
  hotkey      — Press a keyboard shortcut (SENSITIVE)
"""

from __future__ import annotations

from typing import Any, List

from harma.tools.base import BaseTool, PermissionLevel, ToolResult
from harma.config.logging_config import get_logger

log = get_logger(__name__)


class TypeTextTool(BaseTool):
    name = "type_text"
    description = (
        "Types a string of text using the keyboard. "
        "Use this after clicking a text field to enter text. "
        "Handles regular text; for special characters use the clipboard method."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to type.",
            },
            "use_clipboard": {
                "type": "boolean",
                "description": (
                    "If true, use clipboard paste instead of keystroke simulation. "
                    "More reliable for special characters and Unicode text. "
                    "Default: false."
                ),
            },
        },
        "required": ["text"],
    }

    async def execute(
        self,
        text: str,
        use_clipboard: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        from harma.computer.keyboard import type_text, type_text_clipboard
        if use_clipboard:
            result = type_text_clipboard(text)
        else:
            result = type_text(text)
        return ToolResult(
            success=result.success,
            output=result.to_text(),
            data=result.to_dict(),
            error=result.error,
        )


class PressKeyTool(BaseTool):
    name = "press_key"
    description = (
        "Presses and releases a single keyboard key. "
        "Examples: 'enter', 'tab', 'escape', 'f5', 'delete', 'backspace', "
        "'up', 'down', 'left', 'right', 'home', 'end'."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": (
                    "Key to press. Use lowercase names: 'enter', 'tab', 'escape', "
                    "'backspace', 'delete', 'f1'-'f12', 'up', 'down', 'left', 'right'."
                ),
            },
        },
        "required": ["key"],
    }

    async def execute(self, key: Any, **kwargs: Any) -> ToolResult:
        from harma.computer.keyboard import press_key
        result = press_key(key)
        return ToolResult(
            success=result.success,
            output=result.to_text(),
            data=result.to_dict(),
            error=result.error,
        )


class HotkeyTool(BaseTool):
    name = "hotkey"
    description = (
        "Presses a keyboard shortcut (combination of keys simultaneously). "
        "Accepts a list of keys e.g. ['ctrl', 'c'], or shortcut string e.g. 'ctrl+t', 'ctrl+c', 'alt+f4'."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "keys": {
                "description": (
                    "List of keys or shortcut string to press together. "
                    "Example: ['ctrl', 'c'] or 'ctrl+t' or ['ctrl', 'shift', 'esc']."
                ),
            },
        },
        "required": ["keys"],
    }

    async def execute(self, keys: Any, **kwargs: Any) -> ToolResult:
        from harma.computer.keyboard import hotkey
        result = hotkey(keys)
        return ToolResult(
            success=result.success,
            output=result.to_text(),
            data=result.to_dict(),
            error=result.error,
        )

