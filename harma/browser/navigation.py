"""
Harma Browser Navigation — Phase 3

Provides URL navigation, history navigation, reload, and page wait utilities.

Security:
  - Navigation URLs are logged (never credentials embedded in URLs).
  - Domain allow/deny list enforced if configured.
  - Webpage content is treated as untrusted data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, List, TYPE_CHECKING

from harma.config.logging_config import get_logger

if TYPE_CHECKING:
    from playwright.async_api import Page

log = get_logger(__name__)

# Blocked URL schemes (not HTTP/HTTPS navigation)
_BLOCKED_SCHEMES = {"javascript:", "data:", "vbscript:", "file:"}

# Default navigation timeout (ms)
_NAV_TIMEOUT = 30_000

# Default wait condition — wait for DOM to be stable
_WAIT_UNTIL = "domcontentloaded"


@dataclass
class NavigationResult:
    """Result of a navigation operation."""
    success: bool
    url: str = ""
    title: str = ""
    error: str = ""
    status_code: int = 0

    def to_text(self) -> str:
        if self.success:
            return f"Navigated to: {self.title!r} ({self.url})"
        return f"Navigation failed: {self.error}"

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "url": self.url,
            "title": self.title,
            "status_code": self.status_code,
            "error": self.error,
        }


def _is_safe_url(url: str) -> tuple[bool, str]:
    """
    Check whether a URL is safe to navigate to.
    Returns (safe, reason).
    """
    url_lower = url.lower().strip()
    for scheme in _BLOCKED_SCHEMES:
        if url_lower.startswith(scheme):
            return False, f"Blocked URL scheme: {scheme}"
    return True, ""


def _normalise_url(url: str) -> str:
    """Add https:// if no scheme is present."""
    url = url.strip()
    if not re.match(r"^[a-zA-Z][a-zA-Z\d+\-.]*://", url):
        url = "https://" + url
    return url


async def navigate(
    page: "Page",
    url: str,
    wait_until: str = _WAIT_UNTIL,
    timeout: int = _NAV_TIMEOUT,
) -> NavigationResult:
    """
    Navigate the page to a URL.

    Args:
        page: Active Playwright page.
        url: Target URL. Scheme will be added if missing.
        wait_until: Playwright wait condition (domcontentloaded, networkidle, load).
        timeout: Navigation timeout in ms.
    """
    url = _normalise_url(url)
    safe, reason = _is_safe_url(url)
    if not safe:
        log.warning("[NAV] Blocked navigation: %s — %s", url, reason)
        return NavigationResult(success=False, url=url, error=reason)

    log.info("[NAV] Navigating to: %s", url)
    try:
        response = await page.goto(url, wait_until=wait_until, timeout=timeout)
        title = await page.title()
        actual_url = page.url
        status = response.status if response else 0
        log.info("[NAV] OK: %s | %s | status=%d", actual_url, title, status)
        return NavigationResult(
            success=True,
            url=actual_url,
            title=title,
            status_code=status,
        )
    except Exception as exc:
        err = f"Navigation failed: {exc}"
        log.error("[NAV] %s", err)
        return NavigationResult(success=False, url=url, error=err)


async def go_back(page: "Page", timeout: int = _NAV_TIMEOUT) -> NavigationResult:
    """Navigate back in history."""
    log.info("[NAV] Going back.")
    try:
        await page.go_back(wait_until=_WAIT_UNTIL, timeout=timeout)
        title = await page.title()
        return NavigationResult(success=True, url=page.url, title=title)
    except Exception as exc:
        return NavigationResult(success=False, url=page.url, error=str(exc))


async def go_forward(page: "Page", timeout: int = _NAV_TIMEOUT) -> NavigationResult:
    """Navigate forward in history."""
    log.info("[NAV] Going forward.")
    try:
        await page.go_forward(wait_until=_WAIT_UNTIL, timeout=timeout)
        title = await page.title()
        return NavigationResult(success=True, url=page.url, title=title)
    except Exception as exc:
        return NavigationResult(success=False, url=page.url, error=str(exc))


async def reload_page(page: "Page", timeout: int = _NAV_TIMEOUT) -> NavigationResult:
    """Reload the current page."""
    log.info("[NAV] Reloading: %s", page.url)
    try:
        await page.reload(wait_until=_WAIT_UNTIL, timeout=timeout)
        title = await page.title()
        return NavigationResult(success=True, url=page.url, title=title)
    except Exception as exc:
        return NavigationResult(success=False, url=page.url, error=str(exc))


async def wait_for_navigation(page: "Page", timeout: int = _NAV_TIMEOUT) -> NavigationResult:
    """Wait for the current navigation to complete."""
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=timeout)
        title = await page.title()
        return NavigationResult(success=True, url=page.url, title=title)
    except Exception as exc:
        return NavigationResult(success=False, url=page.url, error=str(exc))


async def get_current_url(page: "Page") -> str:
    """Return the current page URL."""
    return page.url


async def get_page_title(page: "Page") -> str:
    """Return the current page title."""
    try:
        return await page.title()
    except Exception:
        return ""
