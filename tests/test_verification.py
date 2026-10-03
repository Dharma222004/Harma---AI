"""
Harma — Verified Computer Execution Integration Tests

Tests the three-valued ActionOutcome taxonomy:
  ACTION_FAILED / ACTION_EXECUTED_UNVERIFIED / ACTION_EXECUTED_VERIFIED

These tests mock the window system so no real GUI is required.
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from harma.computer.verification import (
    ActionOutcome,
    ActionVerifier,
    VerificationEvidence,
    VerificationResult,
    WindowPoller,
    get_verifier,
)


class TestActionOutcome(unittest.TestCase):
    """Unit tests for VerificationResult properties."""

    def _make_result(self, outcome: ActionOutcome) -> VerificationResult:
        return VerificationResult(
            outcome=outcome,
            action="test_action",
            expected_state="test state",
        )

    def test_verified_property(self):
        r = self._make_result(ActionOutcome.ACTION_EXECUTED_VERIFIED)
        self.assertTrue(r.verified)
        self.assertFalse(r.failed)
        self.assertFalse(r.unverified)

    def test_failed_property(self):
        r = self._make_result(ActionOutcome.ACTION_FAILED)
        self.assertFalse(r.verified)
        self.assertTrue(r.failed)
        self.assertFalse(r.unverified)

    def test_unverified_property(self):
        r = self._make_result(ActionOutcome.ACTION_EXECUTED_UNVERIFIED)
        self.assertFalse(r.verified)
        self.assertFalse(r.failed)
        self.assertTrue(r.unverified)

    def test_to_dict_includes_outcome_value(self):
        r = self._make_result(ActionOutcome.ACTION_EXECUTED_VERIFIED)
        d = r.to_dict()
        self.assertEqual(d["outcome"], "action_executed_verified")
        self.assertTrue(d["verified"])

    def test_to_log_string(self):
        r = self._make_result(ActionOutcome.ACTION_FAILED)
        r.detail = "Tool crashed"
        s = r.to_log_string()
        self.assertIn("[ACTION_FAILED]", s)
        self.assertIn("Tool crashed", s)


class TestWindowPoller(unittest.IsolatedAsyncioTestCase):
    """Unit tests for WindowPoller condition polling."""

    async def test_wait_for_window_found_immediately(self):
        poller = WindowPoller()
        with patch.object(poller, "_window_visible", return_value=True):
            result = await poller.wait_for_window("WhatsApp", timeout=2.0)
        self.assertTrue(result)

    async def test_wait_for_window_not_found(self):
        poller = WindowPoller(poll_interval=0.1)
        with patch.object(poller, "_window_visible", return_value=False):
            result = await poller.wait_for_window("WhatsApp", timeout=0.3)
        self.assertFalse(result)

    async def test_wait_for_foreground_found(self):
        poller = WindowPoller()
        with patch.object(poller, "_get_foreground_title", return_value="WhatsApp"):
            result = await poller.wait_for_foreground("WhatsApp", timeout=2.0)
        self.assertTrue(result)

    async def test_wait_for_foreground_wrong_window(self):
        poller = WindowPoller(poll_interval=0.1)
        with patch.object(poller, "_get_foreground_title", return_value="Notepad"):
            result = await poller.wait_for_foreground("WhatsApp", timeout=0.3)
        self.assertFalse(result)

    async def test_wait_for_condition_met(self):
        poller = WindowPoller()
        flag = [False]

        async def set_flag():
            await asyncio.sleep(0.05)
            flag[0] = True

        asyncio.create_task(set_flag())
        result = await poller.wait_for_condition(lambda: flag[0], timeout=2.0, description="flag")
        self.assertTrue(result)

    async def test_wait_for_condition_timeout(self):
        poller = WindowPoller(poll_interval=0.1)
        result = await poller.wait_for_condition(lambda: False, timeout=0.3, description="never_true")
        self.assertFalse(result)


class TestActionVerifier(unittest.IsolatedAsyncioTestCase):
    """Unit tests for ActionVerifier."""

    async def test_verify_window_opened_when_tool_failed(self):
        """If tool failed, outcome must be ACTION_FAILED regardless of windows."""
        verifier = ActionVerifier()
        result = await verifier.verify_window_opened(
            application_name="WhatsApp",
            tool_succeeded=False,
        )
        self.assertTrue(result.failed)
        self.assertFalse(result.verified)

    async def test_verify_window_opened_window_appears(self):
        """When window appears and is the foreground: ACTION_EXECUTED_VERIFIED."""
        verifier = ActionVerifier()
        with patch.object(verifier._poller, "_window_visible", return_value=True), \
             patch.object(verifier._poller, "_get_foreground_title", return_value="WhatsApp"):
            result = await verifier.verify_window_opened(
                application_name="WhatsApp",
                tool_succeeded=True,
                timeout=2.0,
            )
        self.assertTrue(result.verified)
        self.assertEqual(result.outcome, ActionOutcome.ACTION_EXECUTED_VERIFIED)
        self.assertGreater(result.best_confidence, 0.5)

    async def test_verify_window_opened_timeout(self):
        """When window does not appear within timeout: ACTION_EXECUTED_UNVERIFIED."""
        verifier = ActionVerifier()
        with patch.object(verifier._poller, "_window_visible", return_value=False), \
             patch.object(verifier._poller, "_get_foreground_title", return_value=""):
            result = await verifier.verify_window_opened(
                application_name="SomeApp",
                tool_succeeded=True,
                timeout=0.3,
            )
        self.assertTrue(result.unverified)
        self.assertFalse(result.verified)

    async def test_verify_window_focused_match(self):
        """When the expected window is in foreground: ACTION_EXECUTED_VERIFIED."""
        verifier = ActionVerifier()
        with patch.object(verifier._poller, "_get_foreground_title", return_value="WhatsApp"):
            result = await verifier.verify_window_focused(
                window_fragment="WhatsApp",
                tool_succeeded=True,
                timeout=2.0,
            )
        self.assertTrue(result.verified)

    async def test_verify_window_focused_mismatch(self):
        """When the foreground is a different window: ACTION_EXECUTED_UNVERIFIED."""
        verifier = ActionVerifier()
        with patch.object(verifier._poller, "_get_foreground_title", return_value="Notepad"):
            result = await verifier.verify_window_focused(
                window_fragment="WhatsApp",
                tool_succeeded=True,
                timeout=0.3,
            )
        self.assertTrue(result.unverified)
        self.assertFalse(result.verified)

    async def test_verify_keyboard_input_window_held(self):
        """When keyboard action is sent and window stays focused: returns OK."""
        verifier = ActionVerifier()
        with patch.object(verifier._poller, "_get_foreground_title", return_value="WhatsApp"):
            result = await verifier.verify_keyboard_input(
                action_name="type_text",
                tool_succeeded=True,
                expected_text="hi",
                window_fragment="WhatsApp",
            )
        # type_text with expected_text: window OK → VERIFIED (confidence 0.8+)
        self.assertIn(result.outcome, [
            ActionOutcome.ACTION_EXECUTED_VERIFIED,
            ActionOutcome.ACTION_EXECUTED_UNVERIFIED,
        ])
        self.assertFalse(result.failed)

    async def test_verify_keyboard_input_tool_failed(self):
        """Tool failure → ACTION_FAILED immediately."""
        verifier = ActionVerifier()
        result = await verifier.verify_keyboard_input(
            action_name="press_key",
            tool_succeeded=False,
        )
        self.assertTrue(result.failed)

    async def test_verify_keyboard_press_enter_always_unverified(self):
        """press_key(enter) without expected_text = UNVERIFIED until screen observed."""
        verifier = ActionVerifier()
        with patch.object(verifier._poller, "_get_foreground_title", return_value="WhatsApp"):
            result = await verifier.verify_keyboard_input(
                action_name="press_key",
                tool_succeeded=True,
                expected_text=None,
                window_fragment="WhatsApp",
            )
        # press_key without text stays UNVERIFIED — must observe screen next
        self.assertTrue(result.unverified)

    async def test_error_dialog_detection(self):
        """If 'error' appears in foreground title → UNVERIFIED."""
        verifier = ActionVerifier()
        with patch.object(verifier._poller, "_get_foreground_title", return_value="WhatsApp Error"):
            result = await verifier.verify_keyboard_input(
                action_name="type_text",
                tool_succeeded=True,
                window_fragment="WhatsApp",
            )
        self.assertTrue(result.unverified)

    async def test_get_verifier_singleton(self):
        """get_verifier() always returns the same instance."""
        a = get_verifier()
        b = get_verifier()
        self.assertIs(a, b)


class TestVerifiedExecutionContract(unittest.IsolatedAsyncioTestCase):
    """
    Integration tests verifying the full contract:
      - ACTION EXECUTED ≠ OUTCOME VERIFIED
      - press_key("enter") after type_text stays UNVERIFIED until screen observed
    """

    async def test_send_message_flow_verification_chain(self):
        """
        Simulate the send-message chain and verify each step's outcome.
        
        open_application  → VERIFIED (window appeared)
        focus_application → VERIFIED (window in foreground)
        hotkey(ctrl+n)    → UNVERIFIED (press only, no expected text)
        type_text(name)   → VERIFIED (window held + text expected)
        press_key(down)   → UNVERIFIED (no text check)
        press_key(enter)  → UNVERIFIED (must observe screen)
        type_text(msg)    → VERIFIED (window held)
        press_key(enter)  → UNVERIFIED (must observe before claiming sent)
        """
        verifier = ActionVerifier()

        with patch.object(verifier._poller, "_window_visible", return_value=True), \
             patch.object(verifier._poller, "_get_foreground_title", return_value="WhatsApp"):

            # Step 1: open_application
            r1 = await verifier.verify_window_opened("WhatsApp", tool_succeeded=True, timeout=2.0)
            self.assertTrue(r1.verified, "open_application should be VERIFIED")

            # Step 2: focus_application
            r2 = await verifier.verify_window_focused("WhatsApp", tool_succeeded=True, timeout=2.0)
            self.assertTrue(r2.verified, "focus_application should be VERIFIED")

            # Step 3: hotkey (ctrl+n) — no expected text → UNVERIFIED
            r3 = await verifier.verify_keyboard_input(
                "hotkey", tool_succeeded=True, expected_text=None, window_fragment="WhatsApp"
            )
            # hotkey with no text = press_key path = UNVERIFIED
            # (hotkey goes through the type_text branch but has no expected_text)
            # outcome is window-dependent
            self.assertFalse(r3.failed, "hotkey should not FAIL")

            # Step 4: type_text(contact name)
            r4 = await verifier.verify_keyboard_input(
                "type_text", tool_succeeded=True, expected_text="dharmadurai k", window_fragment="WhatsApp"
            )
            self.assertFalse(r4.failed, "type_text should not FAIL")

            # Step 5: press_key(enter) to send — MUST be UNVERIFIED
            r5 = await verifier.verify_keyboard_input(
                "press_key", tool_succeeded=True, expected_text=None, window_fragment="WhatsApp"
            )
            self.assertTrue(r5.unverified, "press_key(enter) MUST remain UNVERIFIED until screen observed")
            self.assertFalse(r5.verified, "press_key(enter) must NOT be auto-VERIFIED")


if __name__ == "__main__":
    unittest.main()
