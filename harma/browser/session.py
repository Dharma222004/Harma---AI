"""
Harma Browser Session

Wraps a single Playwright browser instance and its page/tab state.

Responsibilities:
  - Own the Playwright browser lifecycle (launch, close)
  - Track all open pages (tabs)
  - Maintain a reference to the currently active page
  - Expose safe accessors used by BrowserController

Design:
  One BrowserSession per Harma session.
  Never construct directly; always go through BrowserController.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field
from typing import Optional, List, TYPE_CHECKING

from harma.config.logging_config import get_logger
from harma.config.settings import ROOT_DIR

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright

log = get_logger(__name__)


@dataclass
class TabInfo:
    """Lightweight metadata about a single browser tab."""
    index: int
    title: str
    url: str
    is_active: bool = False


class BrowserSession:
    """
    Represents an active browser session.

    A session wraps a Playwright Browser + BrowserContext + one or more Pages.
    The session is created by BrowserController.launch() and destroyed by close().
    """

    def __init__(
        self,
        browser_type: str = "msedge" if sys.platform == "win32" else "chromium",
        headless: bool = False,
        profile_dir: Optional[str] = None,
        downloads_path: Optional[str] = None,
        slow_mo: int = 50,
    ) -> None:
        self.browser_type = browser_type
        self.headless = headless
        self.profile_dir = profile_dir
        self.downloads_path = downloads_path
        self.slow_mo = slow_mo

        self._playwright: Optional["Playwright"] = None
        self._browser: Optional["Browser"] = None
        self._context: Optional["BrowserContext"] = None
        self._pages: List["Page"] = []
        self._active_idx: int = 0
        self.is_open: bool = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def launch(self) -> None:
        """Launch the browser and create the default context and page."""
        from playwright.async_api import async_playwright

        log.info("[BROWSER] Launching %s  headless=%s", self.browser_type, self.headless)

        b_type = (self.browser_type or ("msedge" if sys.platform == "win32" else "chromium")).lower()
        channel = None
        if b_type in ("msedge", "edge", "microsoft edge"):
            b_type = "chromium"
            channel = "msedge"
        elif b_type in ("chrome", "google-chrome", "google chrome"):
            b_type = "chromium"
            channel = "chrome"
        elif sys.platform == "win32" and b_type == "chromium":
            channel = "msedge"

        self._playwright = await async_playwright().start()
        launcher = getattr(self._playwright, b_type, self._playwright.chromium)

        launch_kwargs = {
            "headless": self.headless,
            "slow_mo": self.slow_mo,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars",
                "--disable-dev-shm-usage",
            ],
        }
        if channel:
            launch_kwargs["channel"] = channel

        context_kwargs: dict = {
            "viewport": {"width": 1280, "height": 800},
            "locale": "en-US",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
        }
        if self.downloads_path:
            context_kwargs["accept_downloads"] = True

        if self.profile_dir:
            # Persistent context keeps user logged in across sessions (not InPrivate)
            os.makedirs(self.profile_dir, exist_ok=True)
            log.info("[BROWSER] Using persistent profile: %s", self.profile_dir)
            try:
                self._context = await launcher.launch_persistent_context(
                    user_data_dir=self.profile_dir,
                    **launch_kwargs,
                    **context_kwargs,
                )
                self._browser = self._context.browser
            except Exception as exc:
                if "ProcessSingleton" in str(exc) or "Lock file" in str(exc):
                    fallback = os.path.join(ROOT_DIR, "data", "browser_profile")
                    if os.path.abspath(self.profile_dir) != os.path.abspath(fallback):
                        os.makedirs(fallback, exist_ok=True)
                        log.warning("[BROWSER] Profile %s is locked by an existing process. Using fallback persistent profile: %s", self.profile_dir, fallback)
                        self._context = await launcher.launch_persistent_context(
                            user_data_dir=fallback,
                            **launch_kwargs,
                            **context_kwargs,
                        )
                        self._browser = self._context.browser
                    else:
                        log.warning("[BROWSER] Persistent profile %s is locked. Launching standard session.", self.profile_dir)
                        self._browser = await launcher.launch(**launch_kwargs)
                        self._context = await self._browser.new_context(**context_kwargs)
                else:
                    raise
        else:
            self._browser = await launcher.launch(**launch_kwargs)
            self._context = await self._browser.new_context(**context_kwargs)

        try:
            await self._context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = window.chrome || { runtime: {} };
            """)
        except Exception:
            pass

        # In persistent context, Playwright already opens an initial page; reuse it if available
        if self._context.pages:
            page = self._context.pages[0]
        else:
            page = await self._context.new_page()
        self._pages = [page]
        self._active_idx = 0
        self.is_open = True
        self._attach_page_listeners(page)

        log.info("[BROWSER] Browser ready (persistent=%s).", bool(self.profile_dir))

    async def close(self) -> None:
        """Close all pages, context and the browser process."""
        log.info("[BROWSER] Closing browser session.")
        try:
            if self._context:
                await self._context.close()
            if self._browser and self._browser.is_connected():
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as exc:
            log.warning("[BROWSER] Error during close: %s", exc)
        finally:
            self._pages = []
            self._context = None
            self._browser = None
            self._playwright = None
            self.is_open = False
            log.info("[BROWSER] Session closed.")

    # ── Page Management ───────────────────────────────────────────────────────

    @property
    def active_page(self) -> Optional["Page"]:
        """The currently active page/tab."""
        if not self._pages:
            if self._context and self._context.pages:
                self._pages = list(self._context.pages)
                self._active_idx = len(self._pages) - 1
                return self._pages[self._active_idx]
            return None
        idx = min(self._active_idx, len(self._pages) - 1)
        page = self._pages[idx]
        if hasattr(page, "is_closed") and page.is_closed():
            self._pages.remove(page)
            return self.active_page
        return page

    async def new_tab(self, url: str = "") -> "Page":
        """Open a new browser tab, optionally navigate to url."""
        if not self._context:
            raise RuntimeError("Browser not launched.")
        page = await self._context.new_page()
        try:
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        except Exception:
            pass
        self._pages.append(page)
        self._active_idx = len(self._pages) - 1
        self._attach_page_listeners(page)
        if url:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        log.info("[BROWSER] Opened new tab. Total tabs: %d", len(self._pages))
        return page

    async def switch_tab(self, index: int) -> bool:
        """Switch active tab to the given index (0-based). Returns False if invalid."""
        if index < 0 or index >= len(self._pages):
            return False
        self._active_idx = index
        page = self._pages[index]
        await page.bring_to_front()
        log.info("[BROWSER] Switched to tab %d: %s", index, page.url)
        return True

    async def close_tab(self, index: Optional[int] = None) -> bool:
        """Close a tab by index (default: active tab)."""
        idx = index if index is not None else self._active_idx
        if idx < 0 or idx >= len(self._pages):
            return False
        page = self._pages.pop(idx)
        await page.close()
        if self._active_idx >= len(self._pages) and self._pages:
            self._active_idx = len(self._pages) - 1
        log.info("[BROWSER] Closed tab %d. Remaining: %d", idx, len(self._pages))
        return True

    def list_tabs(self) -> List[TabInfo]:
        """Return metadata for all open tabs."""
        tabs = []
        for i, page in enumerate(self._pages):
            try:
                tabs.append(TabInfo(
                    index=i,
                    title=page.url,  # title requires async; use URL as sync proxy
                    url=page.url,
                    is_active=(i == self._active_idx),
                ))
            except Exception:
                pass
        return tabs

    # ── Internal Helpers ──────────────────────────────────────────────────────

    def _attach_page_listeners(self, page: "Page") -> None:
        """Attach lifecycle listeners to a new page."""
        page.on("close", lambda p: self._on_page_closed(p))
        page.on("crash", lambda p: log.error("[BROWSER] Page crashed: %s", getattr(p, "url", "?")))

    def _on_page_closed(self, page: "Page") -> None:
        """Remove a page from tracking when it closes externally."""
        if page in self._pages:
            self._pages.remove(page)
            if self._active_idx >= len(self._pages) and self._pages:
                self._active_idx = len(self._pages) - 1
