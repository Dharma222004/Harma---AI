"""
Harma Browser Package — Phase 3

Provides browser automation via Playwright.

Usage:
    from harma.browser.controller import BrowserController
    ctrl = BrowserController()
    await ctrl.launch()
    await ctrl.navigate("https://google.com")
    obs = await ctrl.observe_page()
    await ctrl.close()
"""

from __future__ import annotations

# Expose top-level controller for convenience
from harma.browser.controller import BrowserController, BrowserSession

__all__ = ["BrowserController", "BrowserSession"]
