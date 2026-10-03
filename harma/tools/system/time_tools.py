"""
Harma System Tools — Phase 1

Includes:
  • get_current_time  — returns current date/time (SAFE)
  • get_system_info   — returns OS & Python info (SAFE)
"""

from __future__ import annotations

import platform
import sys
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from harma.tools.base import BaseTool, PermissionLevel, ToolResult


class GetCurrentTimeTool(BaseTool):
    """Return the current local date and time."""

    name = "get_current_time"
    description = (
        "Returns the current local date and time. "
        "Use this whenever the user asks about the current time, date, day, or year."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": (
                    "Optional IANA timezone name (e.g. 'Asia/Kolkata', 'America/New_York'). "
                    "Defaults to the system local time."
                ),
            }
        },
        "required": [],
    }

    async def execute(self, timezone: str | None = None, **kwargs: Any) -> ToolResult:
        try:
            if timezone:
                tz = ZoneInfo(timezone)
                now = datetime.now(tz)
            else:
                now = datetime.now().astimezone()  # local with offset

            formatted = now.strftime("%A, %d %B %Y  %I:%M %p %Z")
            return ToolResult(
                success=True,
                output=formatted,
                data={"iso": now.isoformat(), "timestamp": now.timestamp()},
            )
        except ZoneInfoNotFoundError:
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown timezone: '{timezone}'. Use an IANA name like 'Asia/Kolkata'.",
            )
        except Exception as exc:
            return ToolResult(success=False, output="", error=str(exc))


class GetSystemInfoTool(BaseTool):
    """Return information about the host system."""

    name = "get_system_info"
    description = (
        "Returns information about the user's operating system, Python version, "
        "machine type, and processor. Useful for troubleshooting."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        info = {
            "os": platform.system(),
            "os_version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": sys.version,
            "node": platform.node(),
        }
        lines = [f"{k}: {v}" for k, v in info.items()]
        return ToolResult(
            success=True,
            output="\n".join(lines),
            data=info,
        )
