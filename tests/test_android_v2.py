"""
Harma Android V2 Integration Tests

Validates the complete Android action stack:
  - Observe => Act => Verify cycle (D2: dispatch != state)
  - FakeAndroidTransport deterministic scenarios
  - WhatsApp send-message end-to-end flow
  - Device controls with state readback verification
  - ElementNotFoundError / DeviceLockedError guard rails
  - UI element resolution priority
  - App management lifecycle
"""

from __future__ import annotations

import unittest

from harma.android.exceptions import (
    AppNotFoundError,
    DeviceLockedError,
    ElementNotFoundError,
)
from harma.android.manager import AndroidManager, set_android_manager
from harma.android.models import AndroidActionResult
from harma.android.transports.mock import FakeAndroidTransport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manager():
    """Return a fresh (manager, transport) pair backed by FakeAndroidTransport."""
    transport = FakeAndroidTransport()
    manager = AndroidManager(transport=transport, auto_connect=True)
    return manager, transport


DEVICE_ID = "emulator-5554"


# ---------------------------------------------------------------------------
# 1. Device Status & Connection
# ---------------------------------------------------------------------------

class TestDeviceStatus(unittest.IsolatedAsyncioTestCase):
    """Verify device status reads correctly from FakeAndroidTransport."""

    async def test_device_status_defaults(self):
        manager, _ = _make_manager()
        status = await manager.get_status(DEVICE_ID)
        self.assertEqual(status.device_id, DEVICE_ID)
        self.assertEqual(status.model, "Pixel 7")
        self.assertEqual(status.manufacturer, "Google")
        self.assertEqual(status.android_version, "14")
        self.assertEqual(status.screen_size, (1080, 2400))
        self.assertFalse(status.is_locked)
        self.assertTrue(status.wifi_enabled)
        self.assertFalse(status.bluetooth_enabled)
        self.assertFalse(status.flashlight_on)

    async def test_list_devices_returns_emulator(self):
        manager, _ = _make_manager()
        devices = await manager.list_devices()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].device_id, DEVICE_ID)

    async def test_connect_and_disconnect(self):
        manager, _ = _make_manager()
        device = await manager.connect(DEVICE_ID)
        self.assertEqual(device.device_id, DEVICE_ID)
        ok = await manager.disconnect(DEVICE_ID)
        self.assertTrue(ok)


# ---------------------------------------------------------------------------
# 2. Screen Observation
# ---------------------------------------------------------------------------

class TestScreenObservation(unittest.IsolatedAsyncioTestCase):
    """Verify observe_screen and observe_ui return correct structured state."""

    async def test_observe_screen_returns_observation(self):
        manager, _ = _make_manager()
        obs = await manager.observe_screen(DEVICE_ID)
        self.assertEqual(obs.device_id, DEVICE_ID)
        self.assertGreater(len(obs.elements), 0)
        self.assertFalse(obs.is_locked)

    async def test_observe_ui_no_screenshot_bytes(self):
        """observe_ui is hierarchy-only: no screenshot bytes."""
        manager, _ = _make_manager()
        obs = await manager.observe_ui(DEVICE_ID)
        self.assertIsNone(obs.screenshot_bytes)
        self.assertGreater(len(obs.elements), 0)

    async def test_whatsapp_screen_elements(self):
        manager, _ = _make_manager()
        await manager.launch_app("WhatsApp", DEVICE_ID)
        obs = await manager.observe_screen(DEVICE_ID)
        self.assertEqual(obs.current_package, "com.whatsapp")
        texts = {el.text for el in obs.elements}
        self.assertIn("WhatsApp", texts)
        self.assertIn("Chats", texts)
        self.assertIn("Alice", texts)
        self.assertIn("Bob", texts)

    async def test_settings_screen_wifi_switch(self):
        manager, _ = _make_manager()
        await manager.launch_app("Settings", DEVICE_ID)
        obs = await manager.observe_screen(DEVICE_ID)
        wifi_switch = obs.find_element("wifi_switch")
        self.assertIsNotNone(wifi_switch)
        self.assertTrue(wifi_switch.checkable)
        self.assertTrue(wifi_switch.checked)  # Wi-Fi ON by default


# ---------------------------------------------------------------------------
# 3. Dispatch vs State Verification (Defect D2)
# ---------------------------------------------------------------------------

class TestDispatchVsStateVerification(unittest.IsolatedAsyncioTestCase):
    """
    Critical D2 contract:
      touch/keyboard actions  => verification="dispatch"
      hardware readbacks      => verification="state"
    """

    async def test_tap_coordinate_is_dispatch(self):
        manager, _ = _make_manager()
        result = await manager.tap(540, 1200, device_id=DEVICE_ID)
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "dispatch")

    async def test_tap_element_no_verify_is_dispatch(self):
        manager, _ = _make_manager()
        await manager.launch_app("WhatsApp", DEVICE_ID)
        result = await manager.tap("Alice", device_id=DEVICE_ID, verify=False)
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "dispatch")

    async def test_tap_element_with_verify_still_dispatch(self):
        """verify=True adds re-observation but result stays dispatch (not state readback)."""
        manager, _ = _make_manager()
        await manager.launch_app("WhatsApp", DEVICE_ID)
        result = await manager.tap("Alice", device_id=DEVICE_ID, verify=True)
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "dispatch",
            "Even with verify=True, tap is still dispatch not a hardware state readback")
        self.assertTrue(result.verified)
        self.assertIn("post_action_screen", result.data)

    async def test_type_text_is_dispatch(self):
        manager, transport = _make_manager()
        result = await manager.type_text("Hello World", DEVICE_ID)
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "dispatch")
        self.assertEqual(transport.typed_text, "Hello World")

    async def test_swipe_is_dispatch(self):
        manager, _ = _make_manager()
        result = await manager.swipe(540, 1500, 540, 900, device_id=DEVICE_ID)
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "dispatch")

    async def test_scroll_down_dispatches_upward_finger_swipe(self):
        """scroll('down') = scroll content down = finger swipes upward (y2 < y1)."""
        manager, transport = _make_manager()
        result = await manager.scroll("down", 600, device_id=DEVICE_ID)
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "dispatch")
        swipes = [h for h in transport.action_history if h["action"] == "swipe"]
        self.assertGreater(len(swipes), 0)
        last = swipes[-1]
        self.assertLess(last["y2"], last["y1"],
            "scroll(down) must swipe finger upward: y2 < y1")

    async def test_press_key_is_dispatch(self):
        manager, _ = _make_manager()
        result = await manager.press_key("BACK", DEVICE_ID)
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "dispatch")

    async def test_flashlight_on_is_state(self):
        """set_flashlight reads back hardware state => verification=state."""
        manager, _ = _make_manager()
        result = await manager.set_flashlight(True, DEVICE_ID)
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "state")
        self.assertTrue(result.verified)
        self.assertTrue(result.data.get("flashlight_on"))

    async def test_flashlight_off_is_state(self):
        manager, transport = _make_manager()
        transport.flashlight_states[DEVICE_ID] = True
        result = await manager.set_flashlight(False, DEVICE_ID)
        self.assertEqual(result.verification, "state")
        self.assertTrue(result.verified)
        self.assertFalse(result.data.get("flashlight_on"))

    async def test_wifi_toggle_is_state(self):
        manager, _ = _make_manager()
        result = await manager.set_wifi(False, DEVICE_ID)
        self.assertEqual(result.verification, "state")
        self.assertTrue(result.verified)
        self.assertFalse(result.data.get("wifi_enabled"))

    async def test_bluetooth_toggle_is_state(self):
        manager, _ = _make_manager()
        result = await manager.set_bluetooth(True, DEVICE_ID)
        self.assertEqual(result.verification, "state")
        self.assertTrue(result.verified)
        self.assertTrue(result.data.get("bluetooth_enabled"))

    async def test_volume_is_state(self):
        manager, _ = _make_manager()
        result = await manager.set_volume(75, device_id=DEVICE_ID)
        self.assertEqual(result.verification, "state")
        self.assertTrue(result.verified)
        self.assertEqual(result.data.get("volume_level"), 75)

    async def test_mobile_data_fallback_is_dispatch_not_state(self):
        """
        Spec 17: Mobile data cannot be changed directly on Android.
        Must NOT claim mobile_data_enabled=True after calling set_mobile_data.
        """
        manager, transport = _make_manager()
        result = await manager.set_mobile_data(True, DEVICE_ID)
        self.assertEqual(result.action, "mobile_data_fallback")
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "dispatch")
        self.assertFalse(result.data.get("direct_modification_supported"))
        actual = await manager.get_mobile_data(DEVICE_ID)
        self.assertFalse(actual, "Mobile data must NOT be falsely reported as enabled")


# ---------------------------------------------------------------------------
# 4. Error Guard Rails
# ---------------------------------------------------------------------------

class TestErrorGuardRails(unittest.IsolatedAsyncioTestCase):

    async def test_tap_nonexistent_element_raises(self):
        manager, _ = _make_manager()
        with self.assertRaises(ElementNotFoundError):
            await manager.tap("nonexistent_button_xyz_404", device_id=DEVICE_ID)

    async def test_tap_on_locked_device_raises(self):
        manager, transport = _make_manager()
        transport.devices[DEVICE_ID].is_locked = True
        with self.assertRaises(DeviceLockedError):
            await manager.tap(540, 1200, device_id=DEVICE_ID)

    async def test_launch_unknown_app_raises(self):
        manager, _ = _make_manager()
        with self.assertRaises(AppNotFoundError):
            await manager.launch_app("UnknownApp12345XYZ", DEVICE_ID)

    async def test_alice_not_on_launcher_screen(self):
        """Alice exists only in WhatsApp. On launcher => ElementNotFoundError."""
        manager, transport = _make_manager()
        self.assertEqual(transport.current_apps[DEVICE_ID][0], "com.android.launcher")
        with self.assertRaises(ElementNotFoundError):
            await manager.tap("Alice", device_id=DEVICE_ID)


# ---------------------------------------------------------------------------
# 5. App Management Lifecycle
# ---------------------------------------------------------------------------

class TestAppManagement(unittest.IsolatedAsyncioTestCase):

    async def test_launch_whatsapp_by_name(self):
        manager, transport = _make_manager()
        result = await manager.launch_app("WhatsApp", DEVICE_ID)
        self.assertTrue(result.success)
        self.assertTrue(result.verified)
        self.assertEqual(result.data.get("package"), "com.whatsapp")
        self.assertEqual(transport.current_apps[DEVICE_ID][0], "com.whatsapp")

    async def test_launch_whatsapp_by_alias(self):
        manager, _ = _make_manager()
        result = await manager.launch_app("wa", DEVICE_ID)
        self.assertTrue(result.success)
        self.assertEqual(result.data.get("package"), "com.whatsapp")

    async def test_launch_settings_by_name(self):
        manager, _ = _make_manager()
        result = await manager.launch_app("Settings", DEVICE_ID)
        self.assertTrue(result.success)
        self.assertEqual(result.data.get("package"), "com.android.settings")

    async def test_close_whatsapp_returns_to_launcher(self):
        manager, transport = _make_manager()
        await manager.launch_app("WhatsApp", DEVICE_ID)
        result = await manager.close_app("WhatsApp", DEVICE_ID)
        self.assertTrue(result.success)
        self.assertTrue(result.verified)
        self.assertNotEqual(transport.current_apps[DEVICE_ID][0], "com.whatsapp")

    async def test_list_apps_includes_whatsapp(self):
        manager, _ = _make_manager()
        apps = await manager.list_apps(DEVICE_ID)
        packages = {a.package for a in apps}
        self.assertIn("com.whatsapp", packages)
        self.assertIn("com.android.settings", packages)

    async def test_get_current_app_after_launch(self):
        manager, _ = _make_manager()
        await manager.launch_app("YouTube", DEVICE_ID)
        app = await manager.get_current_app(DEVICE_ID)
        self.assertEqual(app.name, "YouTube")
        self.assertEqual(app.package, "com.google.android.youtube")


# ---------------------------------------------------------------------------
# 6. UI Element Resolution Priority
# ---------------------------------------------------------------------------

class TestElementResolution(unittest.IsolatedAsyncioTestCase):

    async def test_find_by_full_resource_id(self):
        manager, _ = _make_manager()
        await manager.launch_app("Settings", DEVICE_ID)
        obs = await manager.observe_screen(DEVICE_ID)
        el = obs.find_element("com.android.settings:id/wifi_switch")
        self.assertIsNotNone(el)

    async def test_find_by_resource_id_suffix(self):
        manager, _ = _make_manager()
        await manager.launch_app("Settings", DEVICE_ID)
        obs = await manager.observe_screen(DEVICE_ID)
        el = obs.find_element("wifi_switch")
        self.assertIsNotNone(el)
        self.assertTrue(el.checkable)

    async def test_find_by_content_description(self):
        manager, _ = _make_manager()
        await manager.launch_app("Settings", DEVICE_ID)
        obs = await manager.observe_screen(DEVICE_ID)
        el = obs.find_element("Wi-Fi toggle switch")
        self.assertIsNotNone(el)

    async def test_find_by_exact_text(self):
        manager, _ = _make_manager()
        await manager.launch_app("WhatsApp", DEVICE_ID)
        obs = await manager.observe_screen(DEVICE_ID)
        el = obs.find_element("Chats")
        self.assertIsNotNone(el)
        self.assertEqual(el.text, "Chats")

    async def test_find_by_substring(self):
        manager, _ = _make_manager()
        await manager.launch_app("WhatsApp", DEVICE_ID)
        obs = await manager.observe_screen(DEVICE_ID)
        el = obs.find_element("Al")
        self.assertIsNotNone(el, "Should find Alice via substring Al")

    async def test_alice_center_within_bounds(self):
        manager, _ = _make_manager()
        await manager.launch_app("WhatsApp", DEVICE_ID)
        obs = await manager.observe_screen(DEVICE_ID)
        alice = obs.find_element("Alice")
        self.assertIsNotNone(alice)
        cx, cy = alice.center
        # Bounds for Alice in mock: [150,350][800,430]
        self.assertTrue(150 <= cx <= 800)
        self.assertTrue(350 <= cy <= 430)

    async def test_interactive_elements_are_all_interactive(self):
        manager, _ = _make_manager()
        await manager.launch_app("WhatsApp", DEVICE_ID)
        obs = await manager.observe_screen(DEVICE_ID)
        for el in obs.interactive_elements():
            self.assertTrue(el.clickable or el.checkable or el.scrollable)


# ---------------------------------------------------------------------------
# 7. WhatsApp End-to-End Send Message Flow (D2 Contract)
# ---------------------------------------------------------------------------

class TestWhatsAppSendMessageFlow(unittest.IsolatedAsyncioTestCase):
    """
    Full D2 contract: launch_app = state-verified;
    tap/type_text/press_key = dispatch only (must NOT claim state without re-observe).
    """

    async def test_launch_whatsapp_is_state_verified(self):
        manager, transport = _make_manager()
        result = await manager.launch_app("WhatsApp", DEVICE_ID)
        self.assertTrue(result.success)
        self.assertTrue(result.verified)
        self.assertEqual(transport.current_apps[DEVICE_ID][0], "com.whatsapp")

    async def test_observe_after_launch_confirms_whatsapp(self):
        manager, _ = _make_manager()
        await manager.launch_app("WhatsApp", DEVICE_ID)
        obs = await manager.observe_screen(DEVICE_ID)
        self.assertEqual(obs.current_package, "com.whatsapp")
        self.assertIsNotNone(obs.find_element("Alice"))

    async def test_tap_alice_is_dispatch(self):
        manager, _ = _make_manager()
        await manager.launch_app("WhatsApp", DEVICE_ID)
        result = await manager.tap("Alice", device_id=DEVICE_ID, verify=False)
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "dispatch")
        self.assertNotEqual(result.verification, "state")

    async def test_type_message_is_dispatch(self):
        manager, transport = _make_manager()
        await manager.launch_app("WhatsApp", DEVICE_ID)
        result = await manager.type_text("Hello from Harma!", DEVICE_ID)
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "dispatch")
        self.assertEqual(transport.typed_text, "Hello from Harma!")

    async def test_press_enter_is_dispatch(self):
        manager, _ = _make_manager()
        result = await manager.press_key("ENTER", DEVICE_ID)
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "dispatch")

    async def test_full_flow_action_history(self):
        """Full WhatsApp flow leaves complete audit trail in transport action_history."""
        manager, transport = _make_manager()

        # 1. Launch
        launch = await manager.launch_app("WhatsApp", DEVICE_ID)
        self.assertTrue(launch.success)

        # 2. Observe
        obs = await manager.observe_screen(DEVICE_ID)
        self.assertEqual(obs.current_package, "com.whatsapp")

        # 3. Tap Alice (dispatch)
        tap = await manager.tap("Alice", device_id=DEVICE_ID, verify=False)
        self.assertEqual(tap.verification, "dispatch")

        # 4. Re-observe (confirms still in WhatsApp)
        obs2 = await manager.observe_ui(DEVICE_ID)
        self.assertEqual(obs2.current_package, "com.whatsapp")

        # 5. Type message
        typed = await manager.type_text("Hello, Alice!", DEVICE_ID)
        self.assertEqual(typed.verification, "dispatch")
        self.assertEqual(transport.typed_text, "Hello, Alice!")

        # 6. Send
        send = await manager.press_key("ENTER", DEVICE_ID)
        self.assertEqual(send.verification, "dispatch")

        # Verify audit trail
        acts = {h["action"] for h in transport.action_history}
        self.assertIn("launch_app", acts)
        self.assertIn("tap", acts)
        self.assertIn("type_text", acts)
        self.assertIn("press_key", acts)

    async def test_no_false_state_verification_for_tap(self):
        """tap MUST NOT use verification=state without hardware readback."""
        manager, _ = _make_manager()
        await manager.launch_app("WhatsApp", DEVICE_ID)
        result = await manager.tap("Alice", device_id=DEVICE_ID, verify=False)
        self.assertNotEqual(result.verification, "state",
            "CRITICAL: tap must never claim state verification")
        self.assertEqual(result.verification, "dispatch")


# ---------------------------------------------------------------------------
# 8. Navigation & System Controls
# ---------------------------------------------------------------------------

class TestNavigationAndControls(unittest.IsolatedAsyncioTestCase):

    async def test_home_returns_to_launcher(self):
        manager, transport = _make_manager()
        await manager.launch_app("WhatsApp", DEVICE_ID)
        result = await manager.home(DEVICE_ID)
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "dispatch")
        self.assertEqual(transport.current_apps[DEVICE_ID][0], "com.android.launcher")

    async def test_back_returns_to_launcher(self):
        manager, transport = _make_manager()
        await manager.launch_app("Settings", DEVICE_ID)
        await manager.back(DEVICE_ID)
        self.assertEqual(transport.current_apps[DEVICE_ID][0], "com.android.launcher")

    async def test_navigate_opens_maps(self):
        manager, transport = _make_manager()
        result = await manager.navigate("Bangalore Airport", DEVICE_ID)
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "dispatch")
        self.assertEqual(result.data.get("destination"), "Bangalore Airport")
        self.assertEqual(transport.current_apps[DEVICE_ID][0], "com.google.android.apps.maps")

    async def test_open_camera(self):
        manager, transport = _make_manager()
        result = await manager.open_camera(DEVICE_ID)
        self.assertTrue(result.success)
        self.assertEqual(transport.current_apps[DEVICE_ID][0], "com.android.camera2")

    async def test_lock_and_unlock(self):
        manager, transport = _make_manager()
        await manager.lock(DEVICE_ID)
        self.assertTrue(transport.devices[DEVICE_ID].is_locked)
        await manager.unlock(DEVICE_ID)
        self.assertFalse(transport.devices[DEVICE_ID].is_locked)

    async def test_volume_clamped_to_bounds(self):
        manager, _ = _make_manager()
        r1 = await manager.set_volume(150, device_id=DEVICE_ID)
        self.assertEqual(r1.data.get("volume_level"), 100)
        r2 = await manager.set_volume(-50, device_id=DEVICE_ID)
        self.assertEqual(r2.data.get("volume_level"), 0)

    async def test_clipboard_roundtrip(self):
        manager, _ = _make_manager()
        await manager.set_clipboard("Test content", DEVICE_ID)
        content = await manager.get_clipboard(DEVICE_ID)
        self.assertEqual(content, "Test content")

    async def test_notifications_default(self):
        manager, _ = _make_manager()
        notifications = await manager.get_notifications(DEVICE_ID)
        self.assertGreater(len(notifications), 0)
        wa = [n for n in notifications if n.package == "com.whatsapp"]
        self.assertGreater(len(wa), 0)
        self.assertEqual(wa[0].title, "Mom")


# ---------------------------------------------------------------------------
# 9. AndroidActionResult Taxonomy Serialization
# ---------------------------------------------------------------------------

class TestAndroidActionResultTaxonomy(unittest.TestCase):

    def test_dispatch_verified_null_in_dict(self):
        result = AndroidActionResult(
            success=True, action="tap", detail="Tapped",
            verified=True, verification="dispatch",
        )
        d = result.to_dict()
        self.assertIsNone(d["verified"], "dispatch: verified must be null in serialized output")
        self.assertTrue(d["dispatched"])

    def test_state_verified_true_in_dict(self):
        result = AndroidActionResult(
            success=True, action="flashlight", detail="ON",
            verified=True, verification="state",
            data={"flashlight_on": True},
        )
        d = result.to_dict()
        self.assertTrue(d["verified"])
        self.assertEqual(d["verification"], "state")
        self.assertNotIn("dispatched", d)

    def test_dispatch_failed_dispatched_false(self):
        result = AndroidActionResult(
            success=False, action="tap", detail="Failed",
            verified=False, verification="dispatch",
            error="TRANSPORT_ERROR",
        )
        d = result.to_dict()
        self.assertIsNone(d["verified"])
        self.assertFalse(d["dispatched"])
        self.assertEqual(d["error"], "TRANSPORT_ERROR")

    def test_state_failed_verified_false(self):
        result = AndroidActionResult(
            success=False, action="set_wifi", detail="Failed",
            verified=False, verification="state",
        )
        d = result.to_dict()
        self.assertFalse(d["verified"])
        self.assertNotIn("dispatched", d)


# ---------------------------------------------------------------------------
# 10. Manager Singleton
# ---------------------------------------------------------------------------

class TestManagerSingleton(unittest.TestCase):

    def test_set_android_manager_replaces_singleton(self):
        from harma.android.manager import get_android_manager, set_android_manager
        transport = FakeAndroidTransport()
        manager = AndroidManager(transport=transport, auto_connect=False)
        set_android_manager(manager)
        self.assertIs(get_android_manager(), manager)


if __name__ == "__main__":
    unittest.main()
