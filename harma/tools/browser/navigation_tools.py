"""
Browser Navigation Tools — Phase 3

Exposes browser navigation as Harma tools.

Tools:
  launch_browser    — Open the browser (SAFE)
  close_browser     — Close the browser (SAFE)
  browser_status    — Check if browser is running (SAFE)
  navigate_to       — Go to a URL (SAFE)
  go_back           — Navigate back (SAFE)
  go_forward        — Navigate forward (SAFE)
  reload_page       — Reload current page (SAFE)
  get_current_url   — Get active URL (SAFE)
  get_page_title    — Get active page title (SAFE)
  observe_page      — Full structured page observation (SAFE)
  search_web        — Search using a search engine (SAFE)
"""

from __future__ import annotations

import json
from typing import Any

from harma.tools.base import BaseTool, PermissionLevel, ToolResult
from harma.config.logging_config import get_logger

log = get_logger(__name__)


def _get_ctrl():
    """Lazy-import controller to avoid circular imports at module load."""
    from harma.browser.controller import get_browser_controller
    return get_browser_controller()


class LaunchBrowserTool(BaseTool):
    name = "launch_browser"
    description = (
        "Launches the browser. Supports 'msedge' (Microsoft Edge, default on Windows), "
        "'chrome' (Google Chrome), 'chromium', 'firefox', and 'webkit'. When the user requests Microsoft Edge, "
        "pass browser_type='msedge'. Default is 'msedge' on Windows."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "headless": {
                "type": "boolean",
                "description": "Run browser without visible window (default: false).",
            },
            "browser_type": {
                "type": "string",
                "description": "Browser to launch: 'msedge' (Microsoft Edge, default on Windows), 'chrome' (Google Chrome), 'chromium', 'firefox', 'webkit'. Default: 'msedge' on Windows.",
            },
        },
        "required": [],
    }

    async def execute(self, headless: bool = False, browser_type: Optional[str] = None, **kwargs: Any) -> ToolResult:
        import asyncio
        import sys
        ctrl = _get_ctrl()
        ctrl._headless = headless
        target_b = browser_type or ctrl._browser_type or ("msedge" if sys.platform == "win32" else "chromium")
        if target_b.lower() in ("edge", "microsoft edge"):
            target_b = "msedge"
        elif target_b.lower() in ("chrome", "google chrome", "google-chrome"):
            target_b = "chrome"
        ctrl._browser_type = target_b
        result = await ctrl.launch(browser_type=target_b)
        return ToolResult(
            success=result.success,
            output=result.to_text(),
            data=result.to_dict(),
            error=result.error,
        )



class CloseBrowserTool(BaseTool):
    name = "close_browser"
    description = (
        "Closes the browser session and all open tabs. "
        "The browser can be re-launched with launch_browser."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> ToolResult:
        ctrl = _get_ctrl()
        result = await ctrl.close()
        return ToolResult(
            success=result.success,
            output=result.to_text(),
            data=result.to_dict(),
            error=result.error,
        )


class BrowserStatusTool(BaseTool):
    name = "browser_status"
    description = (
        "Returns the current browser status: whether it is open, "
        "how many tabs are open, and which browser type is running."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> ToolResult:
        ctrl = _get_ctrl()
        status = ctrl.status()
        is_open = status["is_open"]
        detail = (
            f"Browser is {'open' if is_open else 'closed'}. "
            f"Type: {status['browser_type']}. "
            f"Tabs: {status['tab_count']}."
        )
        return ToolResult(success=True, output=detail, data=status)


class NavigateToTool(BaseTool):
    name = "navigate_to"
    description = (
        "Navigates the browser to a URL. "
        "Supports Microsoft Edge ('msedge', default on Windows) or Chrome ('chrome'). "
        "Adds https:// automatically if no scheme is specified. "
        "Returns the final URL and page title after navigation."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to navigate to. Example: 'google.com' or 'https://in.bookmyshow.com'.",
            },
            "browser_type": {
                "type": "string",
                "description": "Browser to use: 'msedge' (Microsoft Edge), 'chrome' (Google Chrome), 'chromium'. Default: 'msedge' on Windows.",
            },
        },
        "required": ["url"],
    }

    async def execute(self, url: str, browser_type: Optional[str] = None, **kwargs: Any) -> ToolResult:
        import sys
        ctrl = _get_ctrl()
        if browser_type:
            b_cand = browser_type.lower()
            if b_cand in ("edge", "microsoft edge"):
                b_cand = "msedge"
            elif b_cand in ("chrome", "google chrome", "google-chrome"):
                b_cand = "chrome"
            ctrl._browser_type = b_cand
        elif not ctrl._browser_type:
            ctrl._browser_type = "msedge" if sys.platform == "win32" else "chromium"
        result = await ctrl.navigate(url)
        return ToolResult(
            success=result.success,
            output=result.to_text(),
            data=result.to_dict(),
            error=result.error,
        )


class GoBackTool(BaseTool):
    name = "go_back"
    description = "Navigates back to the previous page in browser history."
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> ToolResult:
        ctrl = _get_ctrl()
        result = await ctrl.go_back()
        return ToolResult(
            success=result.success, output=result.to_text(),
            data=result.to_dict(), error=result.error,
        )


class GoForwardTool(BaseTool):
    name = "go_forward"
    description = "Navigates forward in browser history."
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> ToolResult:
        ctrl = _get_ctrl()
        result = await ctrl.go_forward()
        return ToolResult(
            success=result.success, output=result.to_text(),
            data=result.to_dict(), error=result.error,
        )


class ReloadPageTool(BaseTool):
    name = "reload_page"
    description = "Reloads the current browser page."
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> ToolResult:
        ctrl = _get_ctrl()
        result = await ctrl.reload()
        return ToolResult(
            success=result.success, output=result.to_text(),
            data=result.to_dict(), error=result.error,
        )


class GetCurrentUrlTool(BaseTool):
    name = "get_current_url"
    description = "Returns the URL of the currently active browser page."
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> ToolResult:
        ctrl = _get_ctrl()
        if not ctrl.is_open:
            return ToolResult(success=False, output="", error="Browser is not open.")
        url = await ctrl.get_url()
        return ToolResult(success=True, output=f"Current URL: {url}", data={"url": url})


class GetPageTitleTool(BaseTool):
    name = "get_page_title"
    description = "Returns the title of the currently active browser page."
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> ToolResult:
        ctrl = _get_ctrl()
        if not ctrl.is_open:
            return ToolResult(success=False, output="", error="Browser is not open.")
        title = await ctrl.get_title()
        return ToolResult(success=True, output=f"Page title: {title}", data={"title": title})


class ObservePageTool(BaseTool):
    name = "observe_page"
    description = (
        "Observes the current browser page and returns structured information: "
        "URL, title, visible text excerpt, buttons, input fields, links, and forms. "
        "Use this after navigation or actions to understand the current page state. "
        "This is the OBSERVE step of OBSERVE → ACT → OBSERVE."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> ToolResult:
        ctrl = _get_ctrl()
        if not ctrl.is_open:
            return ToolResult(success=False, output="", error="Browser is not open.")
        obs = await ctrl.observe()
        if obs.error:
            return ToolResult(success=False, output="", error=obs.error)
        return ToolResult(
            success=True,
            output=obs.to_text(),
            data=obs.to_dict(),
        )


class SearchWebTool(BaseTool):
    name = "search_web"
    description = (
        "Searches the web using a search engine. "
        "Opens the browser if needed, navigates to the search engine, "
        "types the query, and submits it. "
        "Returns the search results page URL and title. "
        "Follow up with observe_page to read the results."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query. Example: 'Nifty 50 performance today'.",
            },
            "engine": {
                "type": "string",
                "description": "Search engine URL (default: 'https://www.google.com').",
            },
        },
        "required": ["query"],
    }

    async def execute(
        self,
        query: str,
        engine: str = "https://www.google.com",
        **kwargs: Any,
    ) -> ToolResult:
        ctrl = _get_ctrl()
        if not ctrl.is_open:
            await ctrl.launch()
        result = await ctrl.search_web(query, engine_url=engine)
        return ToolResult(
            success=result.success,
            output=result.to_text(),
            data=result.data,
            error=result.error,
        )
