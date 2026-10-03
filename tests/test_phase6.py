"""
Harma Phase 6 Test Suite — Android Device Control & Mobile Agent

Comprehensive tests covering:
  1. Device Connection, Discovery, Multi-Device, Status & Lifecycle (Sec 3, 4, 22, 34)
  2. Screen Observation, Screenshots & UI Hierarchy Parser (Sec 5, 6, 7, 28)
  3. Element Resolution Priority (Sec 8)
  4. Touch & Gesture Actions (Tap, Long Press, Swipe, Scroll, Drag) (Sec 9)
  5. Keyboard Actions & System Navigation (Type, Press Key, Home, Back, Recents) (Sec 10, 13)
  6. Application Discovery & Management (List, Find, Launch, Close, Ambiguity) (Sec 11, 12)
  7. Clipboard & Notifications with Privacy Protection (Sec 14, 15, 28, 42)
  8. Security Policy, Authentication Protection & Permission Classification (Sec 23, 24, 25, 26, 27)
  9. Tool Registry Integration & Structured Results (Sec 30, 31)
 10. Observe → Act → Verify Pattern & Failure Recovery (Sec 17, 32, 33)
 11. Section 39 Real-Device Verification Scenarios (Tests 1–7)
 12. Agent Core, Voice & Memory Integration (Sec 18, 20, 21)
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from harma.android.accessibility import UIHierarchyParser
from harma.android.apps import AppManager
from harma.android.clipboard import ClipboardManager
from harma.android.device import DeviceController
from harma.android.exceptions import (
    ActionTimeoutError,
    AmbiguousAppError,
    AndroidError,
    AppNotFoundError,
    DeviceConnectionError,
    DeviceLockedError,
    DeviceNotFoundError,
    ElementNotFoundError,
    MultipleDevicesError,
    SecurityRestrictionError,
    TransportError,
)
from harma.android.input import KEY_CODES, InputController
from harma.android.manager import AndroidManager, set_android_manager
from harma.android.models import (
    AndroidActionResult,
    AndroidDevice,
    AppInfo,
    Bounds,
    DeviceConnectionState,
    DeviceStatus,
    NotificationItem,
    Point,
    ScreenObservation,
    UIElement,
)
from harma.android.notifications import NotificationManager
from harma.android.permissions import AndroidSecurity
from harma.android.screen import ScreenObserver
from harma.android.tools import (
    AndroidBackTool,
    AndroidCloseAppTool,
    AndroidDeviceStatusTool,
    AndroidGetClipboardTool,
    AndroidGetCurrentAppTool,
    AndroidHomeTool,
    AndroidKeyPressTool,
    AndroidLaunchAppTool,
    AndroidListAppsTool,
    AndroidLongPressTool,
    AndroidNotificationsTool,
    AndroidObserveScreenTool,
    AndroidOpenSettingsTool,
    AndroidRecentAppsTool,
    AndroidScreenshotTool,
    AndroidScrollTool,
    AndroidSetClipboardTool,
    AndroidSwipeTool,
    AndroidTapTool,
    AndroidTypeTool,
    get_android_tools,
)
from harma.android.transports.mock import FakeAndroidTransport
from harma.core.agent import HarmaAgent
from harma.core.context import AgentContext
from harma.llm.provider import LLMResponse, Message, Role, ToolCall
from harma.tools.base import PermissionLevel, ToolResult


# ══════════════════════════════════════════════════════════════════════════════
# 1. Device Discovery, Connection, Multi-Device, Status & Lifecycle
# ══════════════════════════════════════════════════════════════════════════════

class TestDeviceLifecycle(unittest.IsolatedAsyncioTestCase):
    """Tests for device discovery, connection, status, multi-device, and lock state."""

    async def asyncSetUp(self) -> None:
        self.transport = FakeAndroidTransport()
        self.manager = AndroidManager(transport=self.transport)

    async def test_list_devices_default(self) -> None:
        devices = await self.manager.list_devices()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].device_id, "emulator-5554")
        self.assertEqual(devices[0].manufacturer, "Google")
        self.assertEqual(devices[0].model, "Pixel 7")
        self.assertEqual(devices[0].state, DeviceConnectionState.CONNECTED)

    async def test_connect_default_device(self) -> None:
        dev = await self.manager.connect()
        self.assertIsNotNone(dev)
        self.assertEqual(dev.device_id, "emulator-5554")
        self.assertEqual(dev.state, DeviceConnectionState.CONNECTED)

    async def test_disconnect_device(self) -> None:
        await self.manager.connect()
        res = await self.manager.disconnect()
        self.assertTrue(res)

    async def test_device_status_inspection(self) -> None:
        status = await self.manager.get_status()
        self.assertIsInstance(status, DeviceStatus)
        self.assertEqual(status.device_id, "emulator-5554")
        self.assertEqual(status.manufacturer, "Google")
        self.assertEqual(status.model, "Pixel 7")
        self.assertEqual(status.screen_size, (1080, 2400))
        self.assertEqual(status.battery_level, 88)
        self.assertTrue(status.is_charging)
        self.assertFalse(status.is_locked)
        self.assertTrue(status.wifi_enabled)

    async def test_multiple_devices_detection(self) -> None:
        dev1 = AndroidDevice(device_id="phone-1", model="Galaxy S23", state=DeviceConnectionState.CONNECTED)
        dev2 = AndroidDevice(device_id="phone-2", model="Pixel 8", state=DeviceConnectionState.CONNECTED)
        multi_transport = FakeAndroidTransport(devices=[dev1, dev2])
        multi_mgr = AndroidManager(transport=multi_transport)

        # Listing devices should show both
        devs = await multi_mgr.list_devices()
        self.assertEqual(len(devs), 2)

        # Connecting without specifying ID must raise MultipleDevicesError
        with self.assertRaises(MultipleDevicesError) as ctx:
            await multi_mgr.connect()
        self.assertIn("phone-1", ctx.exception.device_ids)
        self.assertIn("phone-2", ctx.exception.device_ids)

        # Specifying device ID connects successfully
        connected_dev = await multi_mgr.connect(device_id="phone-2")
        self.assertEqual(connected_dev.device_id, "phone-2")

    async def test_no_devices_error(self) -> None:
        empty_transport = FakeAndroidTransport(devices=[])
        empty_mgr = AndroidManager(transport=empty_transport)
        with self.assertRaises(DeviceNotFoundError):
            await empty_mgr.connect()

    async def test_device_locked_blocks_interaction(self) -> None:
        self.transport.lock_device()
        with self.assertRaises(DeviceLockedError):
            await self.manager.tap(100, y=200)

        # Unlock allows action again
        self.transport.unlock_device()
        res = await self.manager.tap(100, y=200)
        self.assertTrue(res.success)


# ══════════════════════════════════════════════════════════════════════════════
# 2. Screen Observation, Screenshots & UI Hierarchy Parser
# ══════════════════════════════════════════════════════════════════════════════

class TestScreenObservation(unittest.IsolatedAsyncioTestCase):
    """Tests for XML UI hierarchy parsing, screen observation, and bounds."""

    async def asyncSetUp(self) -> None:
        self.transport = FakeAndroidTransport()
        self.manager = AndroidManager(transport=self.transport)
        self.parser = UIHierarchyParser()

    def test_bounds_parsing(self) -> None:
        b = Bounds.from_str("[60,120][1020,240]")
        self.assertEqual(b.left, 60)
        self.assertEqual(b.top, 120)
        self.assertEqual(b.right, 1020)
        self.assertEqual(b.bottom, 240)
        self.assertEqual(b.width, 960)
        self.assertEqual(b.height, 120)
        self.assertEqual(b.center, Point(540, 180))
        self.assertTrue(b.contains(500, 150))
        self.assertFalse(b.contains(10, 10))

    def test_parse_ui_hierarchy_xml(self) -> None:
        xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.android.settings" bounds="[0,0][1080,2400]">
    <node index="0" text="Wi-Fi" resource-id="com.android.settings:id/wifi_settings" class="android.widget.TextView" content-desc="Wi-Fi settings" package="com.android.settings" bounds="[60,540][850,660]" clickable="true" enabled="true" />
    <node index="1" text="ON" resource-id="com.android.settings:id/wifi_switch" class="android.widget.Switch" content-desc="Wi-Fi toggle switch" package="com.android.settings" bounds="[860,540][1020,660]" clickable="true" enabled="true" checkable="true" checked="true" />
  </node>
</hierarchy>"""
        elements = self.parser.parse(xml)
        self.assertEqual(len(elements), 3)  # root frame + 2 children

        wifi_text = next(e for e in elements if e.text == "Wi-Fi")
        self.assertEqual(wifi_text.id, "com.android.settings:id/wifi_settings")
        self.assertEqual(wifi_text.simple_role, "TextView")
        self.assertEqual(wifi_text.center, (455, 600))
        self.assertTrue(wifi_text.clickable)

        wifi_switch = next(e for e in elements if e.simple_role == "Switch")
        self.assertEqual(wifi_switch.text, "ON")
        self.assertTrue(wifi_switch.checked)

    async def test_screen_observation_summary(self) -> None:
        obs = await self.manager.observe_screen()
        self.assertIsInstance(obs, ScreenObservation)
        self.assertEqual(obs.current_package, "com.android.launcher")
        self.assertGreater(len(obs.elements), 0)
        self.assertIn("Google Search", obs.summary)
        self.assertIn("Chrome", obs.summary)

    def test_screen_secret_redaction(self) -> None:
        observer = ScreenObserver(self.transport, detect_secrets=True)
        elements = [
            UIElement(id="login_pass", text="MySuperSecret123", password=True),
            UIElement(id="card_number", text="4111 2222 3333 4444"),
        ]
        observer._redact_secrets(elements)
        self.assertEqual(elements[0].text, "••••••••")
        self.assertEqual(elements[1].text, "[PAYMENT CARD REDACTED]")


# ══════════════════════════════════════════════════════════════════════════════
# 3. Element Resolution Priority
# ══════════════════════════════════════════════════════════════════════════════

class TestElementResolution(unittest.TestCase):
    """Tests for the 8-priority element resolution engine."""

    def setUp(self) -> None:
        self.obs = ScreenObservation(
            device_id="emulator-5554",
            elements=[
                UIElement(
                    id="com.android.settings:id/wifi_entry",
                    role="android.widget.TextView",
                    text="Wi-Fi",
                    content_description="Wi-Fi configuration",
                    bounds=Bounds(100, 200, 300, 250),
                    clickable=True,
                ),
                UIElement(
                    id="com.android.settings:id/search_box",
                    role="android.widget.EditText",
                    text="Search settings",
                    content_description="Search bar",
                    bounds=Bounds(50, 50, 400, 100),
                    clickable=True,
                ),
                UIElement(
                    id="com.android.settings:id/submit_button",
                    role="android.widget.Button",
                    text="Done",
                    content_description="Save changes",
                    bounds=Bounds(200, 500, 300, 550),
                    clickable=True,
                ),
            ],
        )

    def test_priority1_resource_id_resolution(self) -> None:
        el = self.obs.find_element("wifi_entry")
        self.assertIsNotNone(el)
        self.assertEqual(el.id, "com.android.settings:id/wifi_entry")

    def test_priority2_content_description_resolution(self) -> None:
        el = self.obs.find_element("Search bar")
        self.assertIsNotNone(el)
        self.assertEqual(el.id, "com.android.settings:id/search_box")

    def test_priority3_exact_text_resolution(self) -> None:
        el = self.obs.find_element("Wi-Fi")
        self.assertIsNotNone(el)
        self.assertEqual(el.text, "Wi-Fi")

    def test_priority4_case_insensitive_and_substring_resolution(self) -> None:
        el = self.obs.find_element("wi-fi")
        self.assertIsNotNone(el)
        self.assertEqual(el.text, "Wi-Fi")

        el_sub = self.obs.find_element("Search")
        self.assertIsNotNone(el_sub)
        self.assertEqual(el_sub.text, "Search settings")

    def test_priority5_role_resolution(self) -> None:
        el = self.obs.find_element("button")
        self.assertIsNotNone(el)
        self.assertEqual(el.simple_role, "Button")

    def test_element_not_found(self) -> None:
        el = self.obs.find_element("NonExistentElement12345")
        self.assertIsNone(el)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Touch & Gesture Actions
# ══════════════════════════════════════════════════════════════════════════════

class TestTouchActions(unittest.IsolatedAsyncioTestCase):
    """Tests for tap, long press, swipe, scroll, and drag."""

    async def asyncSetUp(self) -> None:
        self.transport = FakeAndroidTransport()
        self.manager = AndroidManager(transport=self.transport)

    async def test_tap_by_coordinates(self) -> None:
        res = await self.manager.tap(100, y=200)
        self.assertTrue(res.success)
        self.assertEqual(res.action, "tap")
        self.assertEqual(res.data["x"], 100)
        self.assertEqual(res.data["y"], 200)

    async def test_long_press(self) -> None:
        res = await self.manager.long_press(150, 300, duration_ms=1200)
        self.assertTrue(res.success)
        self.assertEqual(res.action, "long_press")
        self.assertEqual(res.data["duration_ms"], 1200)

    async def test_swipe(self) -> None:
        res = await self.manager.swipe(100, 800, 100, 200, duration_ms=400)
        self.assertTrue(res.success)
        self.assertEqual(res.action, "swipe")
        self.assertEqual(res.data["from"], (100, 800))
        self.assertEqual(res.data["to"], (100, 200))

    async def test_scroll_down_and_up(self) -> None:
        res_down = await self.manager.scroll("down", distance_px=500)
        self.assertTrue(res_down.success)

        res_up = await self.manager.scroll("up", distance_px=500)
        self.assertTrue(res_up.success)

    async def test_tap_element_resolution_flow(self) -> None:
        # Launcher screen has "Chrome" icon
        res = await self.manager.tap("Chrome")
        self.assertTrue(res.success)
        self.assertEqual(res.action, "tap_element")
        self.assertTrue(res.verified)


# ══════════════════════════════════════════════════════════════════════════════
# 5. Keyboard Actions & System Navigation
# ══════════════════════════════════════════════════════════════════════════════

class TestKeyboardAndNavigation(unittest.IsolatedAsyncioTestCase):
    """Tests for typing, key presses, and system navigation buttons."""

    async def asyncSetUp(self) -> None:
        self.transport = FakeAndroidTransport()
        self.manager = AndroidManager(transport=self.transport)

    async def test_type_text(self) -> None:
        res = await self.manager.type_text("Hello Harma")
        self.assertTrue(res.success)
        self.assertEqual(self.transport.typed_text, "Hello Harma")

    async def test_press_key_enter(self) -> None:
        res = await self.manager.press_key("ENTER")
        self.assertTrue(res.success)
        last_action = self.transport.action_history[-1]
        self.assertEqual(last_action["action"], "press_key")
        self.assertEqual(last_action["key"], "66")

    async def test_system_navigation_home(self) -> None:
        # Launch settings first
        await self.manager.launch_app("Settings")
        app = await self.manager.get_current_app()
        self.assertEqual(app.package, "com.android.settings")

        # Press Home -> returns to launcher
        res = await self.manager.home()
        self.assertTrue(res.success)
        app = await self.manager.get_current_app()
        self.assertEqual(app.package, "com.android.launcher")

    async def test_system_navigation_back(self) -> None:
        await self.manager.launch_app("Settings")
        res = await self.manager.back()
        self.assertTrue(res.success)
        app = await self.manager.get_current_app()
        self.assertEqual(app.package, "com.android.launcher")

    async def test_system_navigation_recent_apps(self) -> None:
        res = await self.manager.recent_apps()
        self.assertTrue(res.success)


# ══════════════════════════════════════════════════════════════════════════════
# 6. Application Discovery & Management
# ══════════════════════════════════════════════════════════════════════════════

class TestAppManagement(unittest.IsolatedAsyncioTestCase):
    """Tests for listing, finding, launching, and closing apps."""

    async def asyncSetUp(self) -> None:
        self.transport = FakeAndroidTransport()
        self.manager = AndroidManager(transport=self.transport)

    async def test_list_installed_apps(self) -> None:
        apps = await self.manager.list_apps()
        self.assertGreater(len(apps), 5)
        names = [a.name for a in apps]
        self.assertIn("WhatsApp", names)
        self.assertIn("Chrome", names)
        self.assertIn("Settings", names)
        self.assertIn("YouTube", names)

    async def test_find_app_exact_and_case_insensitive(self) -> None:
        app1 = await self.manager.app_manager.find_app("emulator-5554", "WhatsApp")
        self.assertEqual(app1.package, "com.whatsapp")

        app2 = await self.manager.app_manager.find_app("emulator-5554", "whatsapp")
        self.assertEqual(app2.package, "com.whatsapp")

    async def test_find_app_alias_match(self) -> None:
        app = await self.manager.app_manager.find_app("emulator-5554", "browser")
        self.assertEqual(app.package, "com.android.chrome")

        app_calc = await self.manager.app_manager.find_app("emulator-5554", "calc")
        self.assertEqual(app_calc.package, "com.google.android.calculator")

    async def test_find_app_package_match(self) -> None:
        app = await self.manager.app_manager.find_app("emulator-5554", "com.google.android.youtube")
        self.assertEqual(app.name, "YouTube")

    async def test_app_not_found_with_suggestions(self) -> None:
        with self.assertRaises(AppNotFoundError) as ctx:
            await self.manager.app_manager.find_app("emulator-5554", "NonExistentAppXYZ")
        self.assertEqual(ctx.exception.code, "APP_NOT_FOUND")

    async def test_launch_app_and_verify(self) -> None:
        res = await self.manager.launch_app("WhatsApp")
        self.assertTrue(res.success)
        self.assertTrue(res.verified)
        self.assertEqual(res.data["package"], "com.whatsapp")

        current = await self.manager.get_current_app()
        self.assertEqual(current.package, "com.whatsapp")

    async def test_close_app_and_verify(self) -> None:
        await self.manager.launch_app("WhatsApp")
        res = await self.manager.close_app("WhatsApp")
        self.assertTrue(res.success)
        self.assertTrue(res.verified)

        current = await self.manager.get_current_app()
        self.assertNotEqual(current.package, "com.whatsapp")


# ══════════════════════════════════════════════════════════════════════════════
# 7. Clipboard & Notifications with Privacy Protection
# ══════════════════════════════════════════════════════════════════════════════

class TestClipboardAndNotifications(unittest.IsolatedAsyncioTestCase):
    """Tests for clipboard get/set and notifications observation."""

    async def asyncSetUp(self) -> None:
        self.transport = FakeAndroidTransport()
        self.manager = AndroidManager(transport=self.transport)

    async def test_clipboard_get_and_set(self) -> None:
        await self.manager.set_clipboard("secret_message_for_clipboard")
        content = await self.manager.get_clipboard()
        self.assertEqual(content, "secret_message_for_clipboard")

    async def test_notifications_retrieval_and_masking(self) -> None:
        notifs = await self.manager.get_notifications()
        self.assertGreater(len(notifs), 0)

        # Check notification attributes
        mom_notif = next((n for n in notifs if n.title == "Mom"), None)
        self.assertIsNotNone(mom_notif)
        self.assertEqual(mom_notif.app_name, "WhatsApp")
        self.assertEqual(mom_notif.text, "Dinner is ready!")

    async def test_otp_in_notification_is_masked(self) -> None:
        # Add an OTP notification
        self.transport.notifications["emulator-5554"].append(
            NotificationItem(
                id="notif_otp",
                package="com.bank.app",
                title="Your Bank OTP Code",
                text="Your verification code is 849201. Do not share.",
            )
        )
        notifs = await self.manager.get_notifications()
        otp_notif = next(n for n in notifs if n.id == "notif_otp")
        self.assertIn("••••••", otp_notif.text)
        self.assertNotIn("849201", otp_notif.text)


# ══════════════════════════════════════════════════════════════════════════════
# 8. Security Policy & Authentication Protection
# ══════════════════════════════════════════════════════════════════════════════

class TestSecurityPolicy(unittest.TestCase):
    """Tests for security barriers preventing authentication bypass."""

    def test_bypass_pin_rejected(self) -> None:
        with self.assertRaises(SecurityRestrictionError):
            AndroidSecurity.validate_action_safety("bypass pin")

    def test_bypass_password_rejected(self) -> None:
        with self.assertRaises(SecurityRestrictionError):
            AndroidSecurity.validate_action_safety("tap", "bypass password")

    def test_bypass_biometric_rejected(self) -> None:
        with self.assertRaises(SecurityRestrictionError):
            AndroidSecurity.validate_action_safety("bypass biometric authentication")

    def test_solve_captcha_rejected(self) -> None:
        with self.assertRaises(SecurityRestrictionError):
            AndroidSecurity.validate_action_safety("solve captcha")

    def test_permission_level_classification(self) -> None:
        self.assertEqual(AndroidSecurity.get_action_permission_level("screenshot"), PermissionLevel.SAFE)
        self.assertEqual(AndroidSecurity.get_action_permission_level("tap"), PermissionLevel.SENSITIVE)
        self.assertEqual(AndroidSecurity.get_action_permission_level("launch_app"), PermissionLevel.SENSITIVE)
        self.assertEqual(AndroidSecurity.get_action_permission_level("uninstall"), PermissionLevel.HIGH_RISK)
        self.assertEqual(AndroidSecurity.get_action_permission_level("factory_reset"), PermissionLevel.HIGH_RISK)


# ══════════════════════════════════════════════════════════════════════════════
# 9. Tool Registry Integration & Structured Results
# ══════════════════════════════════════════════════════════════════════════════

class TestAndroidTools(unittest.IsolatedAsyncioTestCase):
    """Tests for Harma BaseTool implementations and ToolResult conformance."""

    async def asyncSetUp(self) -> None:
        self.transport = FakeAndroidTransport()
        self.manager = AndroidManager(transport=self.transport)
        self.tools = {t.name: t for t in get_android_tools(self.manager)}

    def test_tools_registered_count_and_names(self) -> None:
        expected_names = [
            "android.device_status",
            "android.screenshot",
            "android.observe_screen",
            "android.list_apps",
            "android.current_app",
            "android.launch_app",
            "android.close_app",
            "android.tap",
            "android.long_press",
            "android.swipe",
            "android.scroll",
            "android.type",
            "android.press_key",
            "android.home",
            "android.back",
            "android.recent_apps",
            "android.get_clipboard",
            "android.set_clipboard",
            "android.notifications",
            "android.open_settings",
        ]
        for name in expected_names:
            self.assertIn(name, self.tools, f"Missing tool: {name}")

    async def test_tool_device_status_execution(self) -> None:
        tool = self.tools["android.device_status"]
        res = await tool.execute()
        self.assertIsInstance(res, ToolResult)
        self.assertTrue(res.success)
        self.assertIn("Pixel 7", res.output)

    async def test_tool_screenshot_execution(self) -> None:
        tool = self.tools["android.screenshot"]
        res = await tool.execute()
        self.assertTrue(res.success)
        self.assertIn("Current App", res.output)

    async def test_tool_launch_and_close_app_execution(self) -> None:
        launch_tool = self.tools["android.launch_app"]
        res = await launch_tool.execute(app_name="YouTube")
        self.assertTrue(res.success)
        self.assertIn("Launched 'YouTube'", res.output)

        close_tool = self.tools["android.close_app"]
        res_close = await close_tool.execute(app_name="YouTube")
        self.assertTrue(res_close.success)
        self.assertIn("Closed 'YouTube'", res_close.output)

    async def test_tool_tap_execution(self) -> None:
        tap_tool = self.tools["android.tap"]
        res = await tap_tool.execute(x=100, y=200)
        self.assertTrue(res.success)
        self.assertIn("(100, 200)", res.output)

    async def test_tool_clipboard_execution(self) -> None:
        set_tool = self.tools["android.set_clipboard"]
        res = await set_tool.execute(text="Copied from agent test")
        self.assertTrue(res.success)

        get_tool = self.tools["android.get_clipboard"]
        res_get = await get_tool.execute()
        self.assertTrue(res_get.success)
        self.assertIn("Copied from agent test", res_get.output)


# ══════════════════════════════════════════════════════════════════════════════
# 10. Observe → Act → Verify Pattern & Failure Recovery
# ══════════════════════════════════════════════════════════════════════════════

class TestObserveActVerify(unittest.IsolatedAsyncioTestCase):
    """Tests verifying the observe -> act -> verify loop and recovery behavior."""

    async def asyncSetUp(self) -> None:
        self.transport = FakeAndroidTransport()
        self.manager = AndroidManager(transport=self.transport)

    async def test_observe_act_verify_wifi_toggle(self) -> None:
        # Open Settings screen
        await self.manager.launch_app("Settings")

        # Initial observation: Wi-Fi is ON
        obs1 = await self.manager.observe_screen()
        switch_el1 = next(e for e in obs1.elements if e.simple_role == "Switch")
        self.assertTrue(switch_el1.checked)

        # Tap Wi-Fi toggle switch -> Observe, Tap, Re-observe, Verify
        res = await self.manager.tap("Wi-Fi toggle switch")
        self.assertTrue(res.success)
        self.assertTrue(res.verified)

        # Re-observation confirms state changed
        obs2 = await self.manager.observe_screen()
        switch_el2 = next(e for e in obs2.elements if e.simple_role == "Switch")
        self.assertFalse(switch_el2.checked)

    async def test_missing_element_raises_clean_error(self) -> None:
        with self.assertRaises(ElementNotFoundError) as ctx:
            await self.manager.tap("NonExistentButton999")
        self.assertEqual(ctx.exception.code, "ELEMENT_NOT_FOUND")


# ══════════════════════════════════════════════════════════════════════════════
# 11. Section 39 Real-Device Verification Scenarios (Tests 1–7)
# ══════════════════════════════════════════════════════════════════════════════

class TestSection39Scenarios(unittest.IsolatedAsyncioTestCase):
    """
    Tests covering all 7 real-device testing scenarios specified in Section 39:
      Test 1: "Open Settings" -> Settings opens
      Test 2: "Open Chrome" -> Chrome opens
      Test 3: "Open WhatsApp" -> WhatsApp opens
      Test 4: "Take a screenshot" -> Screenshot captured
      Test 5: "Go home" -> Home screen visible
      Test 6: "Open Settings and show me the Wi-Fi status" -> Observe, identify Wi-Fi, read state
      Test 7: "Open Chrome and search for OpenAI" -> Chrome, search, verify
    """

    async def asyncSetUp(self) -> None:
        self.transport = FakeAndroidTransport()
        self.manager = AndroidManager(transport=self.transport)

    async def test_scenario_1_open_settings(self) -> None:
        res = await self.manager.launch_app("Settings")
        self.assertTrue(res.success)
        self.assertTrue(res.verified)
        app = await self.manager.get_current_app()
        self.assertEqual(app.package, "com.android.settings")

    async def test_scenario_2_open_chrome(self) -> None:
        res = await self.manager.launch_app("Chrome")
        self.assertTrue(res.success)
        self.assertTrue(res.verified)
        app = await self.manager.get_current_app()
        self.assertEqual(app.package, "com.android.chrome")

    async def test_scenario_3_open_whatsapp(self) -> None:
        res = await self.manager.launch_app("WhatsApp")
        self.assertTrue(res.success)
        self.assertTrue(res.verified)
        app = await self.manager.get_current_app()
        self.assertEqual(app.package, "com.whatsapp")

    async def test_scenario_4_take_screenshot(self) -> None:
        obs = await self.manager.screenshot()
        self.assertIsNotNone(obs.screenshot_bytes)
        self.assertGreater(len(obs.elements), 0)

    async def test_scenario_5_go_home(self) -> None:
        await self.manager.launch_app("Chrome")
        res = await self.manager.home()
        self.assertTrue(res.success)
        app = await self.manager.get_current_app()
        self.assertEqual(app.package, "com.android.launcher")

    async def test_scenario_6_open_settings_and_check_wifi_status(self) -> None:
        # Step 1: Open Settings
        await self.manager.launch_app("Settings")
        # Step 2: Observe screen
        obs = await self.manager.observe_screen()
        # Step 3: Locate Wi-Fi
        wifi_el = obs.find_element("Wi-Fi")
        self.assertIsNotNone(wifi_el)
        # Step 4: Locate switch and read state
        switch_el = obs.find_element("Wi-Fi toggle switch")
        self.assertIsNotNone(switch_el)
        self.assertTrue(switch_el.checked)

    async def test_scenario_7_open_chrome_and_search_openai(self) -> None:
        # Step 1: Launch Chrome
        await self.manager.launch_app("Chrome")
        # Step 2: Observe screen to find URL bar
        obs = await self.manager.observe_screen()
        search_box = obs.find_element("Search or type URL")
        self.assertIsNotNone(search_box)
        # Step 3: Tap search field
        tap_res = await self.manager.tap_element(obs.device_id, obs, "Search or type URL")
        self.assertTrue(tap_res.success)
        # Step 4: Type "OpenAI"
        type_res = await self.manager.type_text("OpenAI")
        self.assertTrue(type_res.success)
        self.assertEqual(self.transport.typed_text, "OpenAI")
        # Step 5: Press ENTER
        key_res = await self.manager.press_key("ENTER")
        self.assertTrue(key_res.success)


# ══════════════════════════════════════════════════════════════════════════════
# 12. Agent Core, Voice & Memory Integration
# ══════════════════════════════════════════════════════════════════════════════

class TestAgentAndroidIntegration(unittest.IsolatedAsyncioTestCase):
    """
    Verifies that Android tools integrate seamlessly into HarmaAgent through
    the existing Agent Core, without any independent 'AndroidAgent' loop.
    """

    async def asyncSetUp(self) -> None:
        self.transport = FakeAndroidTransport()
        self.manager = AndroidManager(transport=self.transport)

    async def test_agent_context_registers_android_tools(self) -> None:
        mock_provider = MagicMock()
        mock_provider.name = "mock-llm"
        context = AgentContext(provider=mock_provider, android_manager=self.manager)

        tool_names = [t.name for t in context.registry.list_tools()]
        self.assertIn("android.launch_app", tool_names)
        self.assertIn("android.screenshot", tool_names)
        self.assertIn("android.device_status", tool_names)
        self.assertIn("android.tap", tool_names)
        self.assertIn("android.home", tool_names)

    async def test_agent_loop_executes_android_tool(self) -> None:
        mock_provider = MagicMock()
        mock_provider.name = "mock-llm"

        # Turn 1: LLM decides to call android.launch_app with app_name="WhatsApp"
        # Turn 2: LLM responds "WhatsApp is open."
        mock_provider.complete = AsyncMock(
            side_effect=[
                LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="tc_1",
                            name="android.launch_app",
                            arguments={"app_name": "WhatsApp"},
                        )
                    ],
                ),
                LLMResponse(content="WhatsApp is open.", tool_calls=[]),
            ]
        )

        context = AgentContext(provider=mock_provider, android_manager=self.manager)
        # Enable auto_confirm_sensitive so test doesn't block on prompt
        context.permissions._cfg.auto_confirm_sensitive = True

        agent = HarmaAgent(context=context)
        response = await agent.run("Hey Harma, open WhatsApp.")

        self.assertEqual(response, "WhatsApp is open.")
        current = await self.manager.get_current_app()
        self.assertEqual(current.package, "com.whatsapp")

    async def test_voice_command_routes_through_agent_to_android(self) -> None:
        mock_provider = MagicMock()
        mock_provider.name = "mock-llm"

        # Voice command: "Hey Harma, go home."
        mock_provider.complete = AsyncMock(
            side_effect=[
                LLMResponse(
                    content="",
                    tool_calls=[ToolCall(id="tc_home", name="android.home", arguments={})],
                ),
                LLMResponse(content="Navigated to home screen.", tool_calls=[]),
            ]
        )

        context = AgentContext(provider=mock_provider, android_manager=self.manager)
        agent = HarmaAgent(context=context)

        # Start from inside settings
        await self.manager.launch_app("Settings")
        response = await agent.run("go home")

        self.assertEqual(response, "Navigated to home screen.")
        current = await self.manager.get_current_app()
        self.assertEqual(current.package, "com.android.launcher")


if __name__ == "__main__":
    unittest.main()
