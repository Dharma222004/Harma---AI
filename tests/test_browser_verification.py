"""
Harma Browser D2 Verification Tests

Validates that the browser/controller.py ActionResult correctly implements
the D2 verification taxonomy that mirrors the Android V2 contract:

  dispatch => click, type_text, press_key, scroll, hover, check, uncheck,
              select_option, upload_file
  state    => launch, close, new_tab, switch_tab, close_tab, search_web
  observe  => observe() calls (no side-effect)

All tests run against a pure mock controller (no Playwright / real browser
required). The mock intercepts each action and returns the correct ActionResult
so we can assert verification labels without network or browser dependencies.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import Any, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from harma.browser.controller import ActionResult


# ---------------------------------------------------------------------------
# 1. ActionResult D2 Taxonomy — Unit Tests (no browser needed)
# ---------------------------------------------------------------------------

class TestActionResultTaxonomy(unittest.TestCase):
    """ActionResult.to_dict() must correctly encode the D2 taxonomy."""

    # --- dispatch results ---

    def _dispatch(self, success=True, **kw) -> ActionResult:
        return ActionResult(success=success, action="click", detail="OK",
                            verification="dispatch", **kw)

    def test_dispatch_success_verified_null(self):
        d = self._dispatch().to_dict()
        self.assertIsNone(d["verified"],
            "dispatch: verified must be None (not False, not True)")
        self.assertTrue(d["dispatched"])
        self.assertEqual(d["verification"], "dispatch")

    def test_dispatch_failure_dispatched_false(self):
        d = self._dispatch(success=False, error="TIMEOUT").to_dict()
        self.assertIsNone(d["verified"])
        self.assertFalse(d["dispatched"])
        self.assertEqual(d["error"], "TIMEOUT")

    def test_dispatch_has_no_state_verified_key(self):
        """'verified' must be None for dispatch, never True."""
        d = self._dispatch().to_dict()
        self.assertIsNone(d.get("verified"),
            "dispatch actions MUST NOT carry a truthy verified flag")

    # --- state results ---

    def _state(self, verified=True, **kw) -> ActionResult:
        return ActionResult(success=True, action="launch", detail="OK",
                            verification="state", verified=verified, **kw)

    def test_state_success_verified_true(self):
        d = self._state().to_dict()
        self.assertTrue(d["verified"])
        self.assertEqual(d["verification"], "state")
        self.assertNotIn("dispatched", d)

    def test_state_failure_verified_false(self):
        result = ActionResult(success=False, action="launch", detail="",
                              verification="state", verified=False,
                              error="LAUNCH_ERR")
        d = result.to_dict()
        self.assertFalse(d["verified"])
        self.assertNotIn("dispatched", d)

    # --- observe results ---

    def test_observe_has_no_dispatched_or_verified(self):
        result = ActionResult(success=True, action="observe", detail="OK",
                              verification="observe")
        d = result.to_dict()
        self.assertNotIn("dispatched", d)
        self.assertNotIn("verified", d)

    # --- data field ---

    def test_data_included_when_present(self):
        result = ActionResult(
            success=True, action="search_web", detail="OK",
            verification="state", verified=True,
            data={"url": "https://google.com", "title": "Google"},
        )
        d = result.to_dict()
        self.assertIn("data", d)
        self.assertEqual(d["data"]["url"], "https://google.com")

    def test_data_omitted_when_empty(self):
        result = ActionResult(success=True, action="click", detail="OK",
                              verification="dispatch")
        d = result.to_dict()
        self.assertNotIn("data", d)


# ---------------------------------------------------------------------------
# 2. Interaction Actions are Dispatch (Mock-based)
# ---------------------------------------------------------------------------

class TestInteractionActionsAreDispatch(unittest.IsolatedAsyncioTestCase):
    """
    All user-interaction methods must return verification='dispatch'.
    We mock the Playwright locator/page so we never need a real browser.
    """

    def _make_controller(self):
        """Create a BrowserController with all Playwright calls mocked."""
        from harma.browser.controller import BrowserController
        ctrl = BrowserController.__new__(BrowserController)
        ctrl._browser_type = "chromium"
        ctrl._headless = True
        ctrl._profile_dir = None
        ctrl._nav_count = 0

        # Mock session
        ctrl._session = MagicMock()
        ctrl._session.is_open = True
        ctrl._session._context = MagicMock()

        # Mock page
        mock_page = AsyncMock()
        mock_page.is_closed = MagicMock(return_value=False)
        ctrl._session.active_page = mock_page

        # Patch _ensure_page to always return mock_page
        ctrl._ensure_page = AsyncMock(return_value=mock_page)

        # Mock _download_manager
        from harma.browser.downloads import DownloadManager
        ctrl._download_manager = DownloadManager()

        return ctrl, mock_page

    async def _mock_click(self, description="Submit button"):
        """Helper: mock resolve_element to find an element, then call click()."""
        ctrl, page = self._make_controller()
        mock_locator = AsyncMock()
        mock_resolved = MagicMock()
        mock_resolved.found = True
        mock_resolved.strategy = "aria"
        mock_resolved.error = ""
        with patch("harma.browser.controller.resolve_element",
                   new=AsyncMock(return_value=(mock_locator, mock_resolved))):
            return await ctrl.click(description)

    async def test_click_is_dispatch(self):
        result = await self._mock_click()
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "dispatch")
        self.assertIsNone(result.to_dict()["verified"])

    async def test_click_not_found_is_dispatch(self):
        ctrl, _ = self._make_controller()
        mock_resolved = MagicMock()
        mock_resolved.found = False
        mock_resolved.error = "Element not found"
        with patch("harma.browser.controller.resolve_element",
                   new=AsyncMock(return_value=(None, mock_resolved))):
            result = await ctrl.click("nonexistent button")
        self.assertFalse(result.success)
        self.assertEqual(result.verification, "dispatch")

    async def test_type_text_is_dispatch(self):
        ctrl, _ = self._make_controller()
        mock_locator = AsyncMock()
        mock_resolved = MagicMock()
        mock_resolved.found = True
        mock_resolved.strategy = "css"
        with patch("harma.browser.controller.resolve_element",
                   new=AsyncMock(return_value=(mock_locator, mock_resolved))):
            result = await ctrl.type_text("Search box", "Hello browser!")
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "dispatch")
        self.assertIsNone(result.to_dict()["verified"])

    async def test_press_key_is_dispatch(self):
        ctrl, mock_page = self._make_controller()
        mock_page.keyboard = AsyncMock()
        result = await ctrl.press_key("Enter")
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "dispatch")

    async def test_scroll_page_is_dispatch(self):
        ctrl, mock_page = self._make_controller()
        mock_page.evaluate = AsyncMock()
        result = await ctrl.scroll_page("down", 3)
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "dispatch")
        self.assertIsNone(result.to_dict()["verified"])

    async def test_hover_is_dispatch(self):
        ctrl, _ = self._make_controller()
        mock_locator = AsyncMock()
        mock_resolved = MagicMock()
        mock_resolved.found = True
        with patch("harma.browser.controller.resolve_element",
                   new=AsyncMock(return_value=(mock_locator, mock_resolved))):
            result = await ctrl.hover("Menu item")
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "dispatch")

    async def test_check_is_dispatch(self):
        ctrl, _ = self._make_controller()
        mock_locator = AsyncMock()
        mock_resolved = MagicMock()
        mock_resolved.found = True
        with patch("harma.browser.controller.resolve_element",
                   new=AsyncMock(return_value=(mock_locator, mock_resolved))):
            result = await ctrl.check("Remember me checkbox")
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "dispatch")

    async def test_uncheck_is_dispatch(self):
        ctrl, _ = self._make_controller()
        mock_locator = AsyncMock()
        mock_resolved = MagicMock()
        mock_resolved.found = True
        with patch("harma.browser.controller.resolve_element",
                   new=AsyncMock(return_value=(mock_locator, mock_resolved))):
            result = await ctrl.uncheck("Newsletter checkbox")
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "dispatch")

    async def test_select_option_is_dispatch(self):
        ctrl, _ = self._make_controller()
        mock_locator = AsyncMock()
        mock_resolved = MagicMock()
        mock_resolved.found = True
        with patch("harma.browser.controller.resolve_element",
                   new=AsyncMock(return_value=(mock_locator, mock_resolved))):
            result = await ctrl.select_option("Country dropdown", "India")
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "dispatch")

    async def test_double_click_is_dispatch(self):
        ctrl, _ = self._make_controller()
        mock_locator = AsyncMock()
        mock_resolved = MagicMock()
        mock_resolved.found = True
        mock_resolved.strategy = "text"
        with patch("harma.browser.controller.resolve_element",
                   new=AsyncMock(return_value=(mock_locator, mock_resolved))):
            result = await ctrl.click("File icon", double=True)
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "dispatch")


# ---------------------------------------------------------------------------
# 3. Lifecycle Actions are State (Mock-based)
# ---------------------------------------------------------------------------

class TestLifecycleActionsAreState(unittest.IsolatedAsyncioTestCase):

    async def test_close_when_not_open_is_state(self):
        from harma.browser.controller import BrowserController
        ctrl = BrowserController.__new__(BrowserController)
        ctrl._session = None
        ctrl._browser_type = "chromium"
        ctrl._headless = True
        ctrl._profile_dir = None
        ctrl._nav_count = 0
        from harma.browser.downloads import DownloadManager
        ctrl._download_manager = DownloadManager()
        result = await ctrl.close()
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "state")
        self.assertTrue(result.verified)

    async def test_switch_tab_success_is_state(self):
        from harma.browser.controller import BrowserController
        ctrl = BrowserController.__new__(BrowserController)
        ctrl._session = AsyncMock()
        ctrl._session.switch_tab = AsyncMock(return_value=True)
        result = await ctrl.switch_tab(1)
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "state")
        self.assertTrue(result.verified)

    async def test_switch_tab_failure_is_state_verified_false(self):
        from harma.browser.controller import BrowserController
        ctrl = BrowserController.__new__(BrowserController)
        ctrl._session = AsyncMock()
        ctrl._session.switch_tab = AsyncMock(return_value=False)
        result = await ctrl.switch_tab(99)
        self.assertFalse(result.success)
        self.assertEqual(result.verification, "state")
        self.assertFalse(result.verified)

    async def test_close_tab_success_is_state(self):
        from harma.browser.controller import BrowserController
        ctrl = BrowserController.__new__(BrowserController)
        ctrl._session = AsyncMock()
        ctrl._session.close_tab = AsyncMock(return_value=True)
        result = await ctrl.close_tab(0)
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "state")
        self.assertTrue(result.verified)


# ---------------------------------------------------------------------------
# 4. Navigation is State (URL readback verifies page actually changed)
# ---------------------------------------------------------------------------

class TestNavigationResultContract(unittest.TestCase):
    """
    NavigationResult carries URL/title readback confirming the page changed.
    It is 'state'-equivalent because we have factual post-action proof.
    """

    def test_navigation_result_has_url_and_title(self):
        from harma.browser.navigation import NavigationResult
        result = NavigationResult(
            success=True,
            url="https://example.com",
            title="Example Domain",
            status_code=200,
        )
        d = result.to_dict()
        self.assertTrue(d["success"])
        self.assertEqual(d["url"], "https://example.com")
        self.assertEqual(d["title"], "Example Domain")
        self.assertEqual(d["status_code"], 200)

    def test_navigation_failure_has_error(self):
        from harma.browser.navigation import NavigationResult
        result = NavigationResult(success=False, url="https://bad.url", error="Timeout")
        d = result.to_dict()
        self.assertFalse(d["success"])
        self.assertEqual(d["error"], "Timeout")

    def test_nav_to_text_success(self):
        from harma.browser.navigation import NavigationResult
        result = NavigationResult(success=True, url="https://x.com", title="X (Twitter)")
        self.assertIn("Navigated to", result.to_text())
        self.assertIn("x.com", result.to_text())

    def test_nav_to_text_failure(self):
        from harma.browser.navigation import NavigationResult
        result = NavigationResult(success=False, url="", error="DNS failure")
        self.assertIn("failed", result.to_text())


# ---------------------------------------------------------------------------
# 5. Cross-Platform Taxonomy Invariants
# ---------------------------------------------------------------------------

class TestCrossPlatformTaxonomyInvariants(unittest.TestCase):
    """
    Validate that the Browser D2 taxonomy is consistent with Android V2.
    These tests document and lock the shared contract between platforms.
    """

    def test_dispatch_actions_never_carry_truthy_verified(self):
        """Any dispatch ActionResult must not expose verified=True in to_dict()."""
        dispatch_results = [
            ActionResult(success=True, action="click", verification="dispatch"),
            ActionResult(success=True, action="type_text", verification="dispatch"),
            ActionResult(success=True, action="press_key", verification="dispatch"),
            ActionResult(success=True, action="scroll_page", verification="dispatch"),
            ActionResult(success=True, action="hover", verification="dispatch"),
            ActionResult(success=True, action="check", verification="dispatch"),
            ActionResult(success=True, action="uncheck", verification="dispatch"),
            ActionResult(success=True, action="select_option", verification="dispatch"),
            ActionResult(success=True, action="upload_file", verification="dispatch"),
        ]
        for result in dispatch_results:
            d = result.to_dict()
            self.assertIsNone(d.get("verified"),
                f"action={result.action}: dispatch must have verified=None in to_dict()")

    def test_dispatch_actions_always_carry_dispatched_bool(self):
        """Successful dispatch results must have dispatched=True."""
        result = ActionResult(success=True, action="click", verification="dispatch")
        self.assertTrue(result.to_dict()["dispatched"])
        # Failed dispatch must have dispatched=False
        failed = ActionResult(success=False, action="click", verification="dispatch")
        self.assertFalse(failed.to_dict()["dispatched"])

    def test_state_actions_never_carry_dispatched(self):
        """State results must NOT have a 'dispatched' key."""
        state_results = [
            ActionResult(success=True, action="launch", verification="state", verified=True),
            ActionResult(success=True, action="close", verification="state", verified=True),
            ActionResult(success=True, action="search_web", verification="state", verified=True),
        ]
        for result in state_results:
            d = result.to_dict()
            self.assertNotIn("dispatched", d,
                f"action={result.action}: state must NOT have 'dispatched' key")

    def test_browser_and_android_verification_values_are_identical(self):
        """
        Browser ActionResult and Android AndroidActionResult must use the exact
        same verification string values so the runtime can treat them uniformly.
        """
        from harma.android.models import AndroidActionResult

        browser_dispatch = ActionResult(
            success=True, action="click", verification="dispatch"
        )
        android_dispatch = AndroidActionResult(
            success=True, action="tap", verification="dispatch"
        )
        # Both must serialize 'dispatched' and null 'verified'
        bd = browser_dispatch.to_dict()
        ad = android_dispatch.to_dict()
        self.assertEqual(bd["verification"], ad["verification"])
        self.assertIsNone(bd["verified"])
        self.assertIsNone(ad["verified"])
        self.assertIn("dispatched", bd)
        self.assertIn("dispatched", ad)

        browser_state = ActionResult(
            success=True, action="launch", verification="state", verified=True
        )
        android_state = AndroidActionResult(
            success=True, action="set_wifi", verification="state", verified=True
        )
        bs = browser_state.to_dict()
        aps = android_state.to_dict()
        self.assertEqual(bs["verification"], aps["verification"])
        self.assertTrue(bs["verified"])
        self.assertTrue(aps["verified"])
        self.assertNotIn("dispatched", bs)
        self.assertNotIn("dispatched", aps)

    def test_runtime_can_distinguish_dispatch_from_state(self):
        """
        A runtime function that checks 'is this action confirmed?' must be able
        to distinguish dispatch from state purely from to_dict() output.
        """
        def is_confirmed(action_dict: dict) -> bool:
            """Returns True only if the action is state-verified with verified=True."""
            return (
                action_dict.get("verification") == "state"
                and action_dict.get("verified") is True
            )

        # Dispatch click -> not confirmed (even if success=True)
        click = ActionResult(success=True, action="click", verification="dispatch").to_dict()
        self.assertFalse(is_confirmed(click), "click dispatch must not be confirmed")

        # State launch -> confirmed
        launch = ActionResult(success=True, action="launch",
                              verification="state", verified=True).to_dict()
        self.assertTrue(is_confirmed(launch), "state launch must be confirmed")

        # State failure -> not confirmed
        fail = ActionResult(success=False, action="launch",
                            verification="state", verified=False).to_dict()
        self.assertFalse(is_confirmed(fail))


# ---------------------------------------------------------------------------
# 6. Search Web End-to-End (Mock)
# ---------------------------------------------------------------------------

class TestSearchWebFlow(unittest.IsolatedAsyncioTestCase):
    """search_web returns state verification because it reads back URL/title."""

    async def test_search_web_result_is_state_verified(self):
        from harma.browser.controller import BrowserController
        ctrl = BrowserController.__new__(BrowserController)
        ctrl._browser_type = "chromium"
        ctrl._headless = True
        ctrl._profile_dir = None
        ctrl._nav_count = 0
        ctrl._session = MagicMock()
        ctrl._session.is_open = True
        ctrl._session._context = MagicMock()
        from harma.browser.downloads import DownloadManager
        ctrl._download_manager = DownloadManager()

        mock_page = AsyncMock()
        mock_page.is_closed = MagicMock(return_value=False)
        mock_page.url = "https://www.google.com/search?q=hello"
        mock_page.title = AsyncMock(return_value="hello - Google Search")
        mock_page.wait_for_load_state = AsyncMock()
        ctrl._session.active_page = mock_page
        ctrl._ensure_page = AsyncMock(return_value=mock_page)

        # Mock navigate to succeed
        from harma.browser.navigation import NavigationResult
        with patch.object(ctrl, "navigate",
                          new=AsyncMock(return_value=NavigationResult(
                              success=True, url="https://www.google.com", title="Google",
                          ))):
            with patch.object(ctrl, "get_title",
                              new=AsyncMock(return_value="hello - Google Search")):
                with patch.object(ctrl, "get_url",
                                  new=AsyncMock(return_value="https://www.google.com/search?q=hello")):
                    # simulate typed=True path by mocking page.locator
                    mock_loc = AsyncMock()
                    mock_loc.count = AsyncMock(return_value=1)
                    mock_page.locator = MagicMock(return_value=AsyncMock(
                        first=mock_loc,
                    ))
                    result = await ctrl.search_web("hello")

        # The result must be state-verified (URL readback confirms landing)
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "state",
            "search_web navigates + reads back URL => state verification")
        self.assertTrue(result.verified)
        self.assertEqual(result.data.get("query"), "hello")


if __name__ == "__main__":
    unittest.main()
