"""
Browser Download Tools — Phase 3

File download management tools.

Tools:
  browser_download      — Click a download element (HIGH_RISK — downloads files)
  list_browser_downloads — List recent downloads (SAFE)
"""

from __future__ import annotations

from typing import Any

from harma.tools.base import BaseTool, PermissionLevel, ToolResult
from harma.config.logging_config import get_logger

log = get_logger(__name__)


def _get_ctrl():
    from harma.browser.controller import get_browser_controller
    return get_browser_controller()


class BrowserDownloadTool(BaseTool):
    name = "browser_download"
    description = (
        "Clicks a download link or button and saves the file to the local downloads folder. "
        "Verifies that the file was downloaded successfully. "
        "Describe the element to click (e.g. 'Download PDF button', 'Download report link'). "
        "Files are saved to the Harma downloads directory."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Description of the download link or button to click.",
            }
        },
        "required": ["description"],
    }

    async def execute(self, description: str, **kwargs: Any) -> ToolResult:
        ctrl = _get_ctrl()
        if not ctrl.is_open:
            return ToolResult(success=False, output="", error="Browser is not open.")
        result = await ctrl.click_and_download(description)
        return ToolResult(
            success=result.success,
            output=result.to_text(),
            data=result.to_dict(),
            error=result.error,
        )


class ListBrowserDownloadsTool(BaseTool):
    name = "list_browser_downloads"
    description = (
        "Lists recently downloaded files from the current browser session. "
        "Returns filename, file path, and file size."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum number of recent downloads to return (default: 10).",
            }
        },
        "required": [],
    }

    async def execute(self, limit: int = 10, **kwargs: Any) -> ToolResult:
        ctrl = _get_ctrl()
        downloads = ctrl.list_downloads(limit)
        if not downloads:
            return ToolResult(
                success=True,
                output="No downloads in this session.",
                data={"downloads": []},
            )
        lines = []
        for dl in downloads:
            size_kb = dl.file_size_bytes / 1024
            lines.append(f"  • {dl.filename} ({size_kb:.1f} KB) → {dl.file_path}")
        return ToolResult(
            success=True,
            output="Recent downloads:\n" + "\n".join(lines),
            data={"downloads": [d.__dict__ for d in downloads]},
        )
