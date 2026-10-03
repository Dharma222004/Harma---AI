"""
Computer Control Tools — Phase 1 + 2

Phase 1:
  • open_application — launch any application by name (SAFE)

Phase 2 (stubs for future implementation):
  • screenshot, click, type, press_key, scroll, etc.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from typing import Any

from harma.tools.base import BaseTool, PermissionLevel, ToolResult
from harma.config.logging_config import get_logger

log = get_logger(__name__)


# ── Application aliases ───────────────────────────────────────────────────────
# Maps common spoken names → executable names / commands.
# Extend this dict freely — no agent code changes required.

_APP_MAP_WINDOWS: dict[str, str] = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "firefox": "firefox",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "notepad": "notepad",
    "notepad++": "notepad++",
    "explorer": "explorer",
    "file explorer": "explorer",
    "calculator": "calc",
    "calc": "calc",
    "word": "winword",
    "microsoft word": "winword",
    "excel": "excel",
    "microsoft excel": "excel",
    "powerpoint": "powerpnt",
    "outlook": "outlook",
    "whatsapp": "whatsapp",
    "whatsapp beta": "whatsapp beta",
    "whatsapp business": "whatsapp business",
    "telegram": "telegram",
    "telegram desktop": "telegram",
    "spotify": "spotify",
    "slack": "slack",
    "discord": "discord",
    "code": "code",
    "vs code": "code",
    "visual studio code": "code",
    "cmd": "cmd",
    "command prompt": "cmd",
    "powershell": "powershell",
    "terminal": "wt",          # Windows Terminal
    "windows terminal": "wt",
    "task manager": "taskmgr",
    "paint": "mspaint",
    "vlc": "vlc",
    "zoom": "zoom",
    "teams": "teams",
    "microsoft teams": "teams",
}

_APP_MAP_MAC: dict[str, str] = {
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "firefox": "Firefox",
    "safari": "Safari",
    "finder": "Finder",
    "terminal": "Terminal",
    "notes": "Notes",
    "calendar": "Calendar",
    "mail": "Mail",
    "music": "Music",
    "spotify": "Spotify",
    "slack": "Slack",
    "discord": "Discord",
    "code": "Visual Studio Code",
    "vs code": "Visual Studio Code",
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "telegram desktop": "Telegram",
    "zoom": "zoom.us",
}


_START_APPS_CACHE: Optional[dict[str, str]] = None


def _find_windows_start_app(name: str) -> Optional[str]:
    """
    Search Windows StartApps / UWP packages for modern Windows Store apps
    (e.g. Telegram Desktop, WhatsApp, Spotify, etc.).
    Caches results to avoid repeated PowerShell latency.
    """
    global _START_APPS_CACHE
    if _START_APPS_CACHE is None:
        _START_APPS_CACHE = {}
        try:
            import json
            cmd = ["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                if isinstance(data, list):
                    for item in data:
                        n = item.get("Name", "").strip().lower()
                        aid = item.get("AppID", "").strip()
                        if n and aid:
                            _START_APPS_CACHE[n] = aid
        except Exception as e:
            log.debug("[APP_TOOLS] Get-StartApps lookup failed: %s", e)

    if _START_APPS_CACHE:
        key_lower = name.strip().lower()
        # 1. Exact match takes absolute priority
        if key_lower in _START_APPS_CACHE:
            return f"shell:AppsFolder\\{_START_APPS_CACHE[key_lower]}"

        # 2. Sort candidate apps by length descending so specific variants
        # (e.g. "whatsapp beta", "telegram desktop") are evaluated before base names ("whatsapp")
        sorted_apps = sorted(_START_APPS_CACHE.items(), key=lambda x: len(x[0]), reverse=True)
        for app_name, app_id in sorted_apps:
            if key_lower == app_name:
                return f"shell:AppsFolder\\{app_id}"

        # 3. Whole-word boundary matching (prevent "whatsapp" from matching "whatsapp beta")
        import re
        for app_name, app_id in sorted_apps:
            if re.search(rf"\b{re.escape(app_name)}\b", key_lower):
                return f"shell:AppsFolder\\{app_id}"

        for app_name, app_id in sorted_apps:
            if re.search(rf"\b{re.escape(key_lower)}\b", app_name):
                return f"shell:AppsFolder\\{app_id}"

    return None


def _resolve_app(name: str) -> str:
    """Return the platform-specific launch command/app name."""
    key = name.strip().lower()
    if sys.platform == "win32":
        mapped = _APP_MAP_WINDOWS.get(key, key)
        if os.path.isabs(mapped) and os.path.exists(mapped):
            return mapped

        # 1. Check Windows StartApps / UWP packages FIRST (provides exact AppID for installed modern apps)
        app_id_path = _find_windows_start_app(key)
        if app_id_path:
            return app_id_path

        which = shutil.which(mapped) or shutil.which(f"{mapped}.exe") or shutil.which(f"{key}.exe")
        if which:
            return which
        try:
            import winreg
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for exe_cand in (mapped, f"{mapped}.exe", f"{key}.exe"):
                    try:
                        k = winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_cand}")
                        val = winreg.QueryValue(k, None)
                        if val:
                            clean_val = val.strip('"')
                            if os.path.exists(clean_val):
                                return clean_val
                    except Exception:
                        pass
        except Exception:
            pass
        common_locations: dict[str, list[str]] = {
            "chrome": [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            ],
            "google chrome": [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            ],
            "edge": [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ],
            "microsoft edge": [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ],
            "notepad": [
                r"C:\Windows\System32\notepad.exe",
                r"C:\Windows\notepad.exe",
            ],
            "notepad++": [
                r"C:\Program Files\Notepad++\notepad++.exe",
                r"C:\Program Files (x86)\Notepad++\notepad++.exe",
            ],
            "whatsapp": [
                os.path.expandvars(r"%LOCALAPPDATA%\WhatsApp\WhatsApp.exe"),
                os.path.expandvars(r"%ProgramFiles%\WhatsApp\WhatsApp.exe"),
                "whatsapp:",
            ],
            "telegram": [
                os.path.expandvars(r"%APPDATA%\Telegram Desktop\Telegram.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Telegram Desktop\Telegram.exe"),
                os.path.expandvars(r"%ProgramFiles%\Telegram Desktop\Telegram.exe"),
                "tg:",
            ],
            "telegram desktop": [
                os.path.expandvars(r"%APPDATA%\Telegram Desktop\Telegram.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Telegram Desktop\Telegram.exe"),
                os.path.expandvars(r"%ProgramFiles%\Telegram Desktop\Telegram.exe"),
                "tg:",
            ],
            "calc": [r"C:\Windows\System32\calc.exe"],
            "calculator": [r"C:\Windows\System32\calc.exe"],
        }
        for cand in common_locations.get(key, []):
            if cand.endswith(":") or os.path.exists(cand):
                return cand

        # Check Windows StartApps / UWP packages (e.g. Telegram Desktop, WhatsApp Store app)
        app_id_path = _find_windows_start_app(key)
        if app_id_path:
            return app_id_path

        return mapped
    elif sys.platform == "darwin":
        return _APP_MAP_MAC.get(key, key)
    else:  # linux
        return key


class OpenApplicationTool(BaseTool):
    """Open an application on the user's computer."""

    name = "open_application"
    description = (
        "Opens an application on the user's computer by name. "
        "Use this when the user asks to open, launch, or start any desktop app. "
        "Examples: 'Notepad', 'WhatsApp', 'Telegram', 'Spotify', 'VS Code'. "
        "NOTE: To browse websites, search the web, or extract web page content, "
        "prefer 'launch_browser' or 'navigate_to' so web page automation tools are active."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "application_name": {
                "type": "string",
                "description": "The name of the application to open (e.g. 'Chrome', 'Notepad', 'Telegram').",
            }
        },
        "required": ["application_name"],
    }

    async def execute(self, application_name: str, **kwargs: Any) -> ToolResult:
        resolved = _resolve_app(application_name)
        log.info("Opening application: '%s' → '%s'", application_name, resolved)

        try:
            if sys.platform == "win32":
                # 1. Shell folder (UWP/Store apps) or protocol URI or absolute path or known executable
                if (
                    resolved.startswith("shell:")
                    or ":" in resolved
                    or os.path.isabs(resolved)
                    or resolved.endswith(".exe")
                ):
                    try:
                        os.startfile(resolved)
                        await asyncio.sleep(0.05)
                        return ToolResult(
                            success=True,
                            output=f"Opened {application_name}.",
                            data={"application": application_name, "resolved": resolved},
                        )
                    except Exception as sf_err:
                        log.debug("os.startfile fallback for %s: %s", resolved, sf_err)

                # 2. Check if command is an executable in PATH
                which_cmd = shutil.which(resolved) or shutil.which(f"{resolved}.exe")
                if which_cmd:
                    subprocess.Popen(
                        [which_cmd],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    await asyncio.sleep(0.05)
                    return ToolResult(
                        success=True,
                        output=f"Opened {application_name}.",
                        data={"application": application_name, "resolved": resolved},
                    )

                # 3. If STILL not found, DO NOT execute `start ""` (causes OS modal error dialog)
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"Could not find application '{application_name}' on this computer. "
                        f"Please ensure it is installed and available."
                    ),
                )
            elif sys.platform == "darwin":
                subprocess.Popen(
                    ["open", "-a", resolved],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                subprocess.Popen(
                    resolved,
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            return ToolResult(
                success=True,
                output=f"Opened {application_name}.",
                data={"application": application_name, "resolved": resolved},
            )

        except FileNotFoundError:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Could not find '{resolved}'. "
                    f"Make sure '{application_name}' is installed and on the system PATH."
                ),
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Failed to open '{application_name}': {exc}",
            )


class CloseApplicationTool(BaseTool):
    """Close a running application by name (Windows only in Phase 1)."""

    name = "close_application"
    description = (
        "Closes a running application by its process name. "
        "Use this when the user asks to close or quit an app."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "application_name": {
                "type": "string",
                "description": "Name of the application to close (e.g. 'Chrome', 'Notepad').",
            }
        },
        "required": ["application_name"],
    }

    async def execute(self, application_name: str, **kwargs: Any) -> ToolResult:
        resolved = _resolve_app(application_name)
        # Ensure it ends with .exe on Windows and use basename for taskkill /im
        if sys.platform == "win32":
            base = os.path.basename(resolved)
            if not base.lower().endswith(".exe"):
                process_name = base + ".exe"
            else:
                process_name = base
        else:
            process_name = resolved

        log.info("Closing application: '%s' → '%s'", application_name, process_name)

        try:
            if sys.platform == "win32":
                result = subprocess.run(
                    ["taskkill", "/f", "/im", process_name],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    return ToolResult(
                        success=True,
                        output=f"Closed {application_name}.",
                    )
                else:
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Could not close '{application_name}': {result.stderr.strip()}",
                    )
            elif sys.platform == "darwin":
                subprocess.run(["pkill", "-f", resolved], check=False)
                return ToolResult(success=True, output=f"Closed {application_name}.")
            else:
                subprocess.run(["pkill", "-f", resolved], check=False)
                return ToolResult(success=True, output=f"Closed {application_name}.")

        except Exception as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Failed to close '{application_name}': {exc}",
            )
