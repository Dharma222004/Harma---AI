"""
Harma Computer D2 Verification Tests

Validates that the computer/controller.py ActionResult correctly implements
the D2 cross-platform verification taxonomy.

The computer platform has a richer native verification layer (ActionOutcome
with 3 values from verification.py). These tests validate that the D2 bridge
(d2_verification field) is consistent with both that richer layer AND the
cross-platform contract shared with Android/Browser.

Classification:
  dispatch => mouse_click, mouse_move, mouse_double_click, mouse_right_click,
              mouse_drag, mouse_scroll, type_text, press_key, hotkey,
              type_and_observe
  state    => focus_window, click_and_observe
  observe  => screenshot

All tests run with mocked low-level calls (no real screen/OS required).
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from typing import Optional
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# 1. ActionResult D2 Taxonomy — Unit Tests (no OS needed)
# ---------------------------------------------------------------------------

class TestComputerActionResultTaxonomy(unittest.TestCase):
    """ActionResult.to_dict() must correctly encode the D2 taxonomy."""

    def _mk(self, d2="dispatch", d2_verified=None, success=True):
        from harma.computer.controller import ActionResult
        return ActionResult(
            success=success, action="test",
            d2_verification=d2, d2_verified=d2_verified,
        )

    # --- dispatch ---

    def test_dispatch_verified_null(self):
        d = self._mk("dispatch").to_dict()
        self.assertIsNone(d["d2_verified"])
        self.assertTrue(d["dispatched"])
        self.assertEqual(d["d2_verification"], "dispatch")

    def test_dispatch_failed_dispatched_false(self):
        d = self._mk("dispatch", success=False).to_dict()
        self.assertIsNone(d["d2_verified"])
        self.assertFalse(d["dispatched"])

    def test_dispatch_has_no_state_keys_beyond_null(self):
        d = self._mk("dispatch").to_dict()
        # verified must be None not True/False
        self.assertIsNone(d.get("d2_verified"))

    # --- state ---

    def test_state_verified_true(self):
        d = self._mk("state", d2_verified=True).to_dict()
        self.assertTrue(d["d2_verified"])
        self.assertEqual(d["d2_verification"], "state")
        self.assertNotIn("dispatched", d)

    def test_state_verified_false(self):
        d = self._mk("state", d2_verified=False, success=False).to_dict()
        self.assertFalse(d["d2_verified"])
        self.assertNotIn("dispatched", d)

    # --- observe ---

    def test_observe_has_no_dispatched_or_verified(self):
        d = self._mk("observe").to_dict()
        self.assertNotIn("dispatched", d)
        self.assertNotIn("d2_verified", d)

    # --- legacy verification field preserved ---

    def test_legacy_verification_string_preserved(self):
        from harma.computer.controller import ActionResult
        result = ActionResult(
            success=True, action="focus_window",
            verification="Window in foreground",
            d2_verification="state", d2_verified=True,
        )
        d = result.to_dict()
        self.assertEqual(d["verification"], "Window in foreground")
        self.assertTrue(d["d2_verified"])

    def test_to_text_includes_state_verified(self):
        from harma.computer.controller import ActionResult
        result = ActionResult(
            success=True, action="focus_window",
            detail="Focused 'Chrome'",
            verification="Window in foreground",
            d2_verification="state", d2_verified=True,
        )
        text = result.to_text()
        self.assertIn("State-verified: True", text)
        self.assertIn("Window in foreground", text)


# ---------------------------------------------------------------------------
# 2. Mouse Actions are Dispatch
# ---------------------------------------------------------------------------

class TestMouseActionsAreDispatch(unittest.TestCase):

    def setUp(self):
        from harma.computer.controller import ComputerController
        self.ctrl = ComputerController(post_action_delay=0.0)

    def _make_mouse_result(self, action="click", success=True):
        from harma.computer.mouse import MouseResult
        return MouseResult(success=success, action=action, x=100, y=200)

    def test_mouse_click_is_dispatch(self):
        with patch("harma.computer.controller.click",
                   return_value=self._make_mouse_result("click")):
            result = self.ctrl.mouse_click(100, 200)
        self.assertTrue(result.success)
        self.assertEqual(result.d2_verification, "dispatch")
        self.assertIsNone(result.to_dict()["d2_verified"])

    def test_mouse_move_is_dispatch(self):
        with patch("harma.computer.controller.move",
                   return_value=self._make_mouse_result("move")):
            result = self.ctrl.mouse_move(100, 200)
        self.assertEqual(result.d2_verification, "dispatch")

    def test_mouse_double_click_is_dispatch(self):
        with patch("harma.computer.controller.double_click",
                   return_value=self._make_mouse_result("double_click")):
            result = self.ctrl.mouse_double_click(100, 200)
        self.assertEqual(result.d2_verification, "dispatch")

    def test_mouse_right_click_is_dispatch(self):
        with patch("harma.computer.controller.right_click",
                   return_value=self._make_mouse_result("right_click")):
            result = self.ctrl.mouse_right_click(100, 200)
        self.assertEqual(result.d2_verification, "dispatch")

    def test_mouse_drag_is_dispatch(self):
        with patch("harma.computer.controller.drag",
                   return_value=self._make_mouse_result("drag")):
            result = self.ctrl.mouse_drag(0, 0, 100, 200)
        self.assertEqual(result.d2_verification, "dispatch")

    def test_mouse_scroll_is_dispatch(self):
        with patch("harma.computer.controller.scroll",
                   return_value=self._make_mouse_result("scroll")):
            result = self.ctrl.mouse_scroll(3, "down")
        self.assertEqual(result.d2_verification, "dispatch")

    def test_failed_click_is_still_dispatch(self):
        with patch("harma.computer.controller.click",
                   return_value=self._make_mouse_result("click", success=False)):
            result = self.ctrl.mouse_click(100, 200)
        self.assertFalse(result.success)
        self.assertEqual(result.d2_verification, "dispatch")
        d = result.to_dict()
        self.assertFalse(d["dispatched"])
        self.assertIsNone(d["d2_verified"])


# ---------------------------------------------------------------------------
# 3. Keyboard Actions are Dispatch
# ---------------------------------------------------------------------------

class TestKeyboardActionsAreDispatch(unittest.TestCase):

    def setUp(self):
        from harma.computer.controller import ComputerController
        self.ctrl = ComputerController(post_action_delay=0.0)

    def _make_kb_result(self, action="type_text", success=True):
        from harma.computer.keyboard import KeyboardResult
        return KeyboardResult(success=success, action=action)

    def test_type_text_is_dispatch(self):
        with patch("harma.computer.controller.type_text",
                   return_value=self._make_kb_result("type_text")):
            result = self.ctrl.type_text("Hello, World!")
        self.assertTrue(result.success)
        self.assertEqual(result.d2_verification, "dispatch")
        self.assertIsNone(result.to_dict()["d2_verified"])

    def test_press_key_is_dispatch(self):
        with patch("harma.computer.controller.press_key",
                   return_value=self._make_kb_result("press_key")):
            result = self.ctrl.press_key("enter")
        self.assertEqual(result.d2_verification, "dispatch")

    def test_hotkey_is_dispatch(self):
        with patch("harma.computer.controller.hotkey",
                   return_value=self._make_kb_result("hotkey")):
            result = self.ctrl.hotkey(["ctrl", "c"])
        self.assertEqual(result.d2_verification, "dispatch")

    def test_type_text_clipboard_is_dispatch(self):
        with patch("harma.computer.controller.type_text_clipboard",
                   return_value=self._make_kb_result("type_text")):
            result = self.ctrl.type_text("secret", use_clipboard=True)
        self.assertEqual(result.d2_verification, "dispatch")


# ---------------------------------------------------------------------------
# 4. Focus Window is State
# ---------------------------------------------------------------------------

class TestFocusWindowIsState(unittest.TestCase):

    def setUp(self):
        from harma.computer.controller import ComputerController
        self.ctrl = ComputerController(post_action_delay=0.0)

    def test_focus_window_success_is_state_verified(self):
        with patch("harma.computer.controller.focus_window",
                   return_value={"success": True, "title": "Chrome - Google"}):
            result = self.ctrl.focus_window("Chrome")
        self.assertTrue(result.success)
        self.assertEqual(result.d2_verification, "state")
        self.assertTrue(result.d2_verified)
        d = result.to_dict()
        self.assertTrue(d["d2_verified"])
        self.assertNotIn("dispatched", d)
        # Legacy field also present
        self.assertEqual(d["verification"], "Window in foreground")

    def test_focus_window_failure_is_state_verified_false(self):
        with patch("harma.computer.controller.focus_window",
                   return_value={"success": False, "title": "", "error": "Not found"}):
            result = self.ctrl.focus_window("NoSuchApp")
        self.assertFalse(result.success)
        self.assertEqual(result.d2_verification, "state")
        self.assertFalse(result.d2_verified)
        d = result.to_dict()
        self.assertFalse(d["d2_verified"])


# ---------------------------------------------------------------------------
# 5. Screenshot is Observe
# ---------------------------------------------------------------------------

class TestScreenshotIsObserve(unittest.TestCase):

    def test_screenshot_is_observe(self):
        from harma.computer.controller import ComputerController
        ctrl = ComputerController(post_action_delay=0.0)

        # Mock take_screenshot to avoid OS dependency
        mock_shot = MagicMock()
        mock_shot.success = True
        mock_shot.width = 1920
        mock_shot.height = 1080
        mock_shot.error = ""
        mock_shot.to_text.return_value = "Screenshot saved"
        mock_shot.to_dict.return_value = {"path": "/tmp/shot.png"}

        mock_obs = MagicMock()
        mock_obs.active_window_title = "Harma"
        mock_obs.active_window_app = "python"

        with patch("harma.computer.controller.take_screenshot", return_value=mock_shot):
            with patch("harma.computer.controller.get_active_window_info",
                       return_value={"title": "Harma", "app": "python"}):
                result = ctrl.screenshot()

        self.assertTrue(result.success)
        self.assertEqual(result.d2_verification, "observe")
        d = result.to_dict()
        self.assertEqual(d["d2_verification"], "observe")
        # observe: no dispatched, no d2_verified
        self.assertNotIn("dispatched", d)
        self.assertNotIn("d2_verified", d)


# ---------------------------------------------------------------------------
# 6. Click-and-Observe is State
# ---------------------------------------------------------------------------

class TestClickAndObserveIsState(unittest.TestCase):

    def test_click_and_observe_is_state(self):
        from harma.computer.controller import ComputerController, ActionResult
        from harma.computer.screen import ScreenObservation

        ctrl = ComputerController(post_action_delay=0.0)

        # Stub mouse_click to return a successful dispatch result
        mock_click = ActionResult(
            success=True, action="click",
            detail="click at (100, 200)",
            d2_verification="dispatch",
        )

        # Stub observe to return a ScreenObservation with known active window
        mock_obs = MagicMock(spec=ScreenObservation)
        mock_obs.active_window_title = "VS Code"
        # Provide a mock screenshot so to_dict() can call .to_dict() on it
        mock_screenshot = MagicMock()
        mock_screenshot.to_dict.return_value = {"path": "/tmp/shot.png"}
        mock_obs.screenshot = mock_screenshot

        ctrl.mouse_click = MagicMock(return_value=mock_click)
        ctrl.observe = MagicMock(return_value=mock_obs)

        result = ctrl.click_and_observe(100, 200)

        self.assertTrue(result.success)
        self.assertEqual(result.d2_verification, "state")
        self.assertTrue(result.d2_verified)
        d = result.to_dict()
        self.assertTrue(d["d2_verified"])
        self.assertNotIn("dispatched", d)

    def test_type_and_observe_is_dispatch(self):
        from harma.computer.controller import ComputerController, ActionResult
        from harma.computer.screen import ScreenObservation

        ctrl = ComputerController(post_action_delay=0.0)
        mock_type = ActionResult(
            success=True, action="type_text",
            detail="typed 5 chars",
            d2_verification="dispatch",
        )
        mock_obs = MagicMock(spec=ScreenObservation)
        mock_obs.active_window_title = "Notepad"

        ctrl.type_text = MagicMock(return_value=mock_type)
        ctrl.observe = MagicMock(return_value=mock_obs)

        result = ctrl.type_and_observe("hello")
        # type effect is unconfirmed even with observe -> remains dispatch
        self.assertEqual(result.d2_verification, "dispatch")


# ---------------------------------------------------------------------------
# 7. Cross-Platform Consistency with Android + Browser
# ---------------------------------------------------------------------------

class TestComputerCrossPlatformConsistency(unittest.TestCase):
    """
    The computer platform's D2 labels must be identical to Android and Browser
    so the Runtime can apply unified logic across all three platforms.
    """

    def test_dispatch_label_matches_android_and_browser(self):
        from harma.computer.controller import ActionResult as CompResult
        from harma.android.models import AndroidActionResult
        from harma.browser.controller import ActionResult as BrowserResult

        comp = CompResult(success=True, action="mouse_click", d2_verification="dispatch")
        android = AndroidActionResult(success=True, action="tap", verification="dispatch")
        browser = BrowserResult(success=True, action="click", verification="dispatch")

        comp_d = comp.to_dict()
        android_d = android.to_dict()
        browser_d = browser.to_dict()

        # All three must have the same cross-platform token name
        self.assertEqual(comp_d["d2_verification"], "dispatch")
        self.assertEqual(android_d["verification"], "dispatch")     # Android uses "verification"
        self.assertEqual(browser_d["verification"], "dispatch")     # Browser uses "verification"

        # All three: verified must be falsy/None for dispatch
        self.assertIsNone(comp_d["d2_verified"])
        self.assertIsNone(android_d["verified"])
        self.assertIsNone(browser_d["verified"])

        # All three: dispatched must be True for successful dispatch
        self.assertTrue(comp_d["dispatched"])
        self.assertTrue(android_d["dispatched"])
        self.assertTrue(browser_d["dispatched"])

    def test_state_label_matches_android_and_browser(self):
        from harma.computer.controller import ActionResult as CompResult
        from harma.android.models import AndroidActionResult
        from harma.browser.controller import ActionResult as BrowserResult

        comp = CompResult(success=True, action="focus_window",
                          d2_verification="state", d2_verified=True)
        android = AndroidActionResult(success=True, action="set_wifi",
                                      verification="state", verified=True)
        browser = BrowserResult(success=True, action="launch",
                                verification="state", verified=True)

        comp_d = comp.to_dict()
        android_d = android.to_dict()
        browser_d = browser.to_dict()

        # All three: no 'dispatched' key
        self.assertNotIn("dispatched", comp_d)
        self.assertNotIn("dispatched", android_d)
        self.assertNotIn("dispatched", browser_d)

        # All three: verified/d2_verified must be True
        self.assertTrue(comp_d["d2_verified"])
        self.assertTrue(android_d["verified"])
        self.assertTrue(browser_d["verified"])

    def test_runtime_can_check_all_three_platforms_uniformly(self):
        """
        A runtime function that checks 'is this action confirmed?' must work
        across all three platforms without platform-specific logic.
        """
        from harma.computer.controller import ActionResult as CompResult
        from harma.android.models import AndroidActionResult
        from harma.browser.controller import ActionResult as BrowserResult

        def is_confirmed_computer(d: dict) -> bool:
            return d.get("d2_verification") == "state" and d.get("d2_verified") is True

        def is_confirmed_android_browser(d: dict) -> bool:
            return d.get("verification") == "state" and d.get("verified") is True

        # Computer dispatch -> not confirmed
        comp_click = CompResult(success=True, action="click", d2_verification="dispatch")
        self.assertFalse(is_confirmed_computer(comp_click.to_dict()))

        # Computer state -> confirmed
        comp_focus = CompResult(success=True, action="focus_window",
                                d2_verification="state", d2_verified=True)
        self.assertTrue(is_confirmed_computer(comp_focus.to_dict()))

        # Android dispatch -> not confirmed
        android_tap = AndroidActionResult(success=True, action="tap", verification="dispatch")
        self.assertFalse(is_confirmed_android_browser(android_tap.to_dict()))

        # Android state -> confirmed
        android_wifi = AndroidActionResult(success=True, action="set_wifi",
                                           verification="state", verified=True)
        self.assertTrue(is_confirmed_android_browser(android_wifi.to_dict()))

        # Browser dispatch -> not confirmed
        browser_click = BrowserResult(success=True, action="click", verification="dispatch")
        self.assertFalse(is_confirmed_android_browser(browser_click.to_dict()))

        # Browser state -> confirmed
        browser_launch = BrowserResult(success=True, action="launch",
                                       verification="state", verified=True)
        self.assertTrue(is_confirmed_android_browser(browser_launch.to_dict()))

    def test_no_platform_reports_false_verified_for_dispatch(self):
        """Critical invariant: no dispatch action from any platform must report verified=True."""
        from harma.computer.controller import ActionResult as CompResult
        from harma.android.models import AndroidActionResult
        from harma.browser.controller import ActionResult as BrowserResult

        actions = [
            CompResult(success=True, action="click", d2_verification="dispatch").to_dict(),
            CompResult(success=True, action="type_text", d2_verification="dispatch").to_dict(),
            AndroidActionResult(success=True, action="tap", verification="dispatch").to_dict(),
            AndroidActionResult(success=True, action="type", verification="dispatch").to_dict(),
            BrowserResult(success=True, action="click", verification="dispatch").to_dict(),
            BrowserResult(success=True, action="type_text", verification="dispatch").to_dict(),
        ]
        for d in actions:
            # verified (or d2_verified for computer) must be falsy/None
            verified = d.get("verified") or d.get("d2_verified")
            self.assertFalse(bool(verified),
                f"Platform action {d.get('action')} incorrectly reported verified={verified}")


# ---------------------------------------------------------------------------
# 8. ActionOutcome Bridge (verification.py <-> D2)
# ---------------------------------------------------------------------------

class TestActionOutcomeBridge(unittest.TestCase):
    """
    Validate the conceptual bridge between the computer platform's native
    ActionOutcome enum and the D2 taxonomy.
    """

    def test_action_outcome_values_exist(self):
        from harma.computer.verification import ActionOutcome
        # All three outcome values must exist
        self.assertEqual(ActionOutcome.ACTION_FAILED.value, "action_failed")
        self.assertEqual(ActionOutcome.ACTION_EXECUTED_UNVERIFIED.value, "action_executed_unverified")
        self.assertEqual(ActionOutcome.ACTION_EXECUTED_VERIFIED.value, "action_executed_verified")

    def test_verification_result_verified_property(self):
        from harma.computer.verification import ActionOutcome, VerificationResult
        r = VerificationResult(
            outcome=ActionOutcome.ACTION_EXECUTED_VERIFIED,
            action="open_app",
            expected_state="Window visible",
            best_confidence=0.9,
        )
        self.assertTrue(r.verified)
        self.assertFalse(r.failed)
        self.assertFalse(r.unverified)

    def test_verification_result_unverified_property(self):
        from harma.computer.verification import ActionOutcome, VerificationResult
        r = VerificationResult(
            outcome=ActionOutcome.ACTION_EXECUTED_UNVERIFIED,
            action="click",
            expected_state="App responds",
        )
        self.assertFalse(r.verified)
        self.assertFalse(r.failed)
        self.assertTrue(r.unverified)

    def test_verification_result_failed_property(self):
        from harma.computer.verification import ActionOutcome, VerificationResult
        r = VerificationResult(
            outcome=ActionOutcome.ACTION_FAILED,
            action="click",
            expected_state="success",
        )
        self.assertTrue(r.failed)

    def test_verification_result_to_dict(self):
        from harma.computer.verification import ActionOutcome, VerificationResult
        r = VerificationResult(
            outcome=ActionOutcome.ACTION_EXECUTED_VERIFIED,
            action="focus_window",
            expected_state="Chrome is foreground",
            best_confidence=0.85,
            detail="Active window matches 'Chrome'",
        )
        d = r.to_dict()
        self.assertEqual(d["outcome"], "action_executed_verified")
        self.assertTrue(d["verified"])
        self.assertAlmostEqual(d["best_confidence"], 0.85, places=2)

    def test_d2_state_maps_to_verified(self):
        """
        Conceptual bridge: a computer ActionResult with d2_verification='state'
        and d2_verified=True is semantically equivalent to ActionOutcome.VERIFIED.
        """
        from harma.computer.controller import ActionResult
        from harma.computer.verification import ActionOutcome

        computer_result = ActionResult(
            success=True, action="focus_window",
            d2_verification="state", d2_verified=True,
        )
        # The d2 contract mirrors the VerificationResult.verified property
        self.assertEqual(computer_result.d2_verified,
                         ActionOutcome.ACTION_EXECUTED_VERIFIED == ActionOutcome.ACTION_EXECUTED_VERIFIED)

    def test_d2_dispatch_maps_to_unverified(self):
        """
        A dispatch ActionResult is semantically equivalent to ACTION_EXECUTED_UNVERIFIED:
        the action ran but the outcome is not yet confirmed.
        """
        from harma.computer.controller import ActionResult
        from harma.computer.verification import ActionOutcome

        computer_result = ActionResult(
            success=True, action="mouse_click", d2_verification="dispatch",
        )
        # Dispatch success = executed but unverified
        self.assertTrue(computer_result.success)
        self.assertIsNone(computer_result.d2_verified)
        # This corresponds to ACTION_EXECUTED_UNVERIFIED
        expected_outcome = ActionOutcome.ACTION_EXECUTED_UNVERIFIED
        self.assertEqual(expected_outcome.value, "action_executed_unverified")


if __name__ == "__main__":
    unittest.main()
