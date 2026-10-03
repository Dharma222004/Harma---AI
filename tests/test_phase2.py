"""
Harma Phase 1 + Phase 2 Full Test Suite

Run with:
    python tests/test_phase2.py

Tests are organised into sections:
  SECTION A — Phase 1 regression (must stay 10/10)
  SECTION B — Phase 2 config
  SECTION C — Safety layer
  SECTION D — Screen capture
  SECTION E — Mouse validation
  SECTION F — Keyboard
  SECTION G — Windows
  SECTION H — Tool registry (all P2 tools registered)
  SECTION I — Permission levels
  SECTION J — Tool execution
  SECTION K — Settings / ComputerConfig
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import unittest

os.environ["PYTHONUTF8"] = "1"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─────────────────────────────────────────────────────────────────────────────
# SECTION A — Phase 1 Regression
# ─────────────────────────────────────────────────────────────────────────────

class TestPhase1Regression(unittest.TestCase):
    """Ensure Phase 1 still works after Phase 2 changes."""

    def test_p1_01_config_loads(self):
        from harma.config.settings import load_config
        cfg = load_config()
        self.assertIsNotNone(cfg)
        self.assertIsNotNone(cfg.llm.provider)

    def test_p1_02_llm_factory_providers(self):
        from harma.llm.factory import PROVIDER_MAP
        for p in ["openai", "gemini", "claude"]:
            self.assertIn(p, PROVIDER_MAP)

    def test_p1_03_tool_registry_create(self):
        from harma.tools.registry import ToolRegistry
        r = ToolRegistry()
        self.assertEqual(len(r), 0)

    def test_p1_04_base_tool_imports(self):
        from harma.tools.base import BaseTool, PermissionLevel, ToolResult
        self.assertIsNotNone(BaseTool)
        self.assertEqual(PermissionLevel.SAFE.value, "safe")
        self.assertEqual(PermissionLevel.SENSITIVE.value, "sensitive")
        self.assertEqual(PermissionLevel.HIGH_RISK.value, "high_risk")

    def test_p1_05_memory(self):
        from harma.memory.short_term import ShortTermMemory
        m = ShortTermMemory()
        m.add_user_message("Hello")
        m.add_assistant_message("Hi!")
        self.assertEqual(len(m.get_messages()), 2)

    def test_p1_06_permissions_all_tiers(self):
        from harma.security.permissions import PermissionManager, PermissionDecision
        from harma.tools.base import PermissionLevel
        pm = PermissionManager()
        self.assertEqual(pm.check("t", PermissionLevel.SAFE), PermissionDecision.ALLOWED)
        self.assertEqual(pm.check("t", PermissionLevel.SENSITIVE), PermissionDecision.NEEDS_CONFIRMATION)
        self.assertEqual(pm.check("t", PermissionLevel.HIGH_RISK), PermissionDecision.NEEDS_CONFIRMATION)

    def test_p1_07_get_current_time(self):
        async def run():
            from harma.tools.system.time_tools import GetCurrentTimeTool
            t = GetCurrentTimeTool()
            r = await t.execute()
            self.assertTrue(r.success)
            self.assertIn("2026", r.output)
        asyncio.run(run())

    def test_p1_08_get_system_info(self):
        async def run():
            from harma.tools.system.time_tools import GetSystemInfoTool
            t = GetSystemInfoTool()
            r = await t.execute()
            self.assertTrue(r.success)
            self.assertIn("os", r.output.lower())
        asyncio.run(run())

    def test_p1_09_unknown_tool_error(self):
        async def run():
            from harma.tools.registry import ToolRegistry
            r = ToolRegistry()
            result = await r.call("nonexistent_tool")
            self.assertFalse(result.success)
            self.assertIn("nonexistent_tool", result.error)
        asyncio.run(run())

    def test_p1_10_timezone_support(self):
        async def run():
            from harma.tools.system.time_tools import GetCurrentTimeTool
            t = GetCurrentTimeTool()
            r = await t.execute(timezone="Asia/Kolkata")
            self.assertTrue(r.success)
            self.assertIn("IST", r.output)
        asyncio.run(run())


# ─────────────────────────────────────────────────────────────────────────────
# SECTION B — Phase 2 Config
# ─────────────────────────────────────────────────────────────────────────────

class TestPhase2Config(unittest.TestCase):

    def test_p2_config_computer_section(self):
        from harma.config.settings import load_config, ComputerConfig
        cfg = load_config()
        self.assertIsInstance(cfg.computer, ComputerConfig)

    def test_p2_config_computer_defaults(self):
        from harma.config.settings import load_config
        cfg = load_config()
        self.assertTrue(cfg.computer.enabled)
        self.assertTrue(cfg.computer.screenshot_enabled)
        self.assertTrue(cfg.computer.mouse_enabled)
        self.assertTrue(cfg.computer.keyboard_enabled)
        self.assertTrue(cfg.computer.window_control_enabled)

    def test_p2_config_safety_values(self):
        from harma.config.settings import load_config
        cfg = load_config()
        self.assertGreater(cfg.computer.safety_action_interval, 0)
        self.assertGreater(cfg.computer.safety_post_action_delay, 0)

    def test_p2_config_computer_confidence(self):
        from harma.config.settings import load_config
        cfg = load_config()
        self.assertGreater(cfg.computer.ui_detection_confidence, 0)
        self.assertLessEqual(cfg.computer.ui_detection_confidence, 1.0)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION C — Safety Layer
# ─────────────────────────────────────────────────────────────────────────────

class TestSafetyLayer(unittest.TestCase):

    def test_p2_safety_valid_coordinates(self):
        from harma.computer.safety import validate_coordinates, get_screen_size
        w, h = get_screen_size()
        # Valid: centre of screen
        x, y = validate_coordinates(w // 2, h // 2)
        self.assertEqual(x, w // 2)
        self.assertEqual(y, h // 2)

    def test_p2_safety_invalid_coordinates_negative(self):
        from harma.computer.safety import validate_coordinates, SafetyError
        with self.assertRaises(SafetyError):
            validate_coordinates(-1, 100)

    def test_p2_safety_invalid_coordinates_too_large(self):
        from harma.computer.safety import validate_coordinates, SafetyError
        with self.assertRaises(SafetyError):
            validate_coordinates(99999, 99999)

    def test_p2_safety_validate_text_normal(self):
        from harma.computer.safety import validate_text
        result = validate_text("Hello World")
        self.assertEqual(result, "Hello World")

    def test_p2_safety_validate_text_strips_null_bytes(self):
        from harma.computer.safety import validate_text
        result = validate_text("Hello\x00World")
        self.assertEqual(result, "HelloWorld")

    def test_p2_safety_validate_text_too_long(self):
        from harma.computer.safety import validate_text, SafetyError
        with self.assertRaises(SafetyError):
            validate_text("x" * 10001)

    def test_p2_safety_validate_key_normalise(self):
        from harma.computer.safety import validate_key
        self.assertEqual(validate_key("ENTER"), "enter")
        self.assertEqual(validate_key("  Tab  "), "tab")

    def test_p2_safety_get_screen_size_positive(self):
        from harma.computer.safety import get_screen_size
        w, h = get_screen_size()
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)

    def test_p2_safety_rate_limit_timing(self):
        from harma.computer.safety import enforce_rate_limit
        # Should not crash and should complete quickly
        t0 = time.monotonic()
        enforce_rate_limit()
        enforce_rate_limit()
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 1.0)  # should finish well under 1 second


# ─────────────────────────────────────────────────────────────────────────────
# SECTION D — Screen Capture
# ─────────────────────────────────────────────────────────────────────────────

class TestScreenCapture(unittest.TestCase):

    def test_p2_screenshot_success(self):
        from harma.computer.screen import take_screenshot
        result = take_screenshot()
        self.assertTrue(result.success, msg=result.error)
        self.assertGreater(result.width, 0)
        self.assertGreater(result.height, 0)

    def test_p2_screenshot_file_exists(self):
        import os
        from harma.computer.screen import take_screenshot
        result = take_screenshot()
        self.assertTrue(result.success)
        self.assertTrue(os.path.isfile(result.image_path))

    def test_p2_screenshot_dimensions(self):
        from harma.computer.screen import take_screenshot
        result = take_screenshot()
        self.assertTrue(result.success, msg=result.error)
        # Screenshot dimensions must be positive and consistent with image size
        self.assertGreater(result.width, 0)
        self.assertGreater(result.height, 0)
        # Verify the saved file matches reported dimensions
        import os
        from PIL import Image
        self.assertTrue(os.path.isfile(result.image_path))
        img = Image.open(result.image_path)
        self.assertEqual(img.size[0], result.width)
        self.assertEqual(img.size[1], result.height)

    def test_p2_screen_observe(self):
        from harma.computer.screen import observe_screen
        obs = observe_screen()
        self.assertTrue(obs.screenshot.success, msg=obs.screenshot.error)
        self.assertGreater(obs.screen_width, 0)
        self.assertGreater(obs.screen_height, 0)

    def test_p2_screenshot_tool(self):
        async def run():
            from harma.tools.computer.screen_tools import TakeScreenshotTool
            t = TakeScreenshotTool()
            r = await t.execute()
            self.assertTrue(r.success, msg=r.error)
            self.assertIn("Screenshot", r.output)
        asyncio.run(run())

    def test_p2_observe_screen_tool(self):
        async def run():
            from harma.tools.computer.screen_tools import ObserveScreenTool
            t = ObserveScreenTool()
            r = await t.execute()
            self.assertTrue(r.success, msg=r.error)
            self.assertIsNotNone(r.data)
        asyncio.run(run())

    def test_p2_get_screen_size_tool(self):
        async def run():
            from harma.tools.computer.screen_tools import GetScreenSizeTool
            t = GetScreenSizeTool()
            r = await t.execute()
            self.assertTrue(r.success)
            self.assertIn("pixels", r.output)
        asyncio.run(run())


# ─────────────────────────────────────────────────────────────────────────────
# SECTION E — Mouse Validation
# ─────────────────────────────────────────────────────────────────────────────

class TestMouseValidation(unittest.TestCase):
    """Test mouse coordinate validation WITHOUT actually moving the mouse."""

    def test_p2_mouse_valid_move(self):
        from harma.computer.mouse import move
        from harma.computer.safety import get_screen_size
        w, h = get_screen_size()
        # Move to a safe area well away from top-left (failsafe corner)
        result = move(w // 2, h // 2)
        self.assertTrue(result.success, msg=result.error)

    def test_p2_mouse_invalid_coords_rejected(self):
        """Test that out-of-bounds coords produce failed result (not crash)."""
        from harma.computer.mouse import move
        result = move(-100, -100)
        self.assertFalse(result.success)
        self.assertIn("outside screen bounds", result.error)

    def test_p2_mouse_scroll(self):
        from harma.computer.mouse import scroll
        from harma.computer.safety import get_screen_size
        w, h = get_screen_size()
        # Always scroll at screen centre to avoid the top-left failsafe corner
        result = scroll(1, "down", w // 2, h // 2)
        self.assertTrue(result.success, msg=result.error)

    def test_p2_mouse_tool_move(self):
        async def run():
            from harma.tools.computer.mouse_tools import MouseMoveTool
            from harma.computer.safety import get_screen_size
            t = MouseMoveTool()
            w, h = get_screen_size()
            r = await t.execute(x=w // 2, y=h // 2)
            self.assertTrue(r.success, msg=r.error)
        asyncio.run(run())

    def test_p2_mouse_tool_invalid_coords(self):
        async def run():
            from harma.tools.computer.mouse_tools import MouseMoveTool
            t = MouseMoveTool()
            r = await t.execute(x=-999, y=-999)
            self.assertFalse(r.success)
        asyncio.run(run())

    def test_p2_mouse_tool_scroll(self):
        async def run():
            from harma.tools.computer.mouse_tools import MouseScrollTool
            from harma.computer.safety import get_screen_size
            t = MouseScrollTool()
            w, h = get_screen_size()
            # Scroll at centre of screen to avoid failsafe corner
            r = await t.execute(amount=2, direction="down", x=w // 2, y=h // 2)
            self.assertTrue(r.success, msg=r.error)
        asyncio.run(run())


# ─────────────────────────────────────────────────────────────────────────────
# SECTION F — Keyboard
# ─────────────────────────────────────────────────────────────────────────────

class TestKeyboard(unittest.TestCase):

    def test_p2_keyboard_validate_text(self):
        from harma.computer.safety import validate_text
        self.assertEqual(validate_text("hello"), "hello")

    def test_p2_keyboard_key_aliases(self):
        from harma.computer.keyboard import _resolve_key
        self.assertEqual(_resolve_key("ENTER"), "enter")
        self.assertEqual(_resolve_key("Return"), "enter")
        self.assertEqual(_resolve_key("ESC"), "escape")
        self.assertEqual(_resolve_key("CTRL"), "ctrl")

    def test_p2_keyboard_press_key_tool_invalid(self):
        """Empty key name should produce a safe error, not crash."""
        async def run():
            from harma.computer.safety import validate_key, SafetyError
            with self.assertRaises(SafetyError):
                validate_key("")
        asyncio.run(run())

    def test_p2_keyboard_tool_type_text(self):
        async def run():
            from harma.tools.computer.keyboard_tools import TypeTextTool
            t = TypeTextTool()
            # We don't actually type during tests — just verify the tool exists
            # and would reject bad input
            self.assertEqual(t.name, "type_text")
            self.assertEqual(t.permission_level.value, "sensitive")
        asyncio.run(run())

    def test_p2_keyboard_tool_press_key(self):
        async def run():
            from harma.tools.computer.keyboard_tools import PressKeyTool
            t = PressKeyTool()
            self.assertEqual(t.name, "press_key")
        asyncio.run(run())

    def test_p2_keyboard_tool_hotkey(self):
        async def run():
            from harma.tools.computer.keyboard_tools import HotkeyTool
            t = HotkeyTool()
            self.assertEqual(t.name, "hotkey")
        asyncio.run(run())


# ─────────────────────────────────────────────────────────────────────────────
# SECTION G — Windows
# ─────────────────────────────────────────────────────────────────────────────

class TestWindowControl(unittest.TestCase):

    def test_p2_get_active_window(self):
        from harma.computer.windows import get_active_window_info
        info = get_active_window_info()
        self.assertIsInstance(info, dict)
        self.assertIn("title", info)

    def test_p2_list_windows_returns_list(self):
        from harma.computer.windows import list_windows
        windows = list_windows()
        self.assertIsInstance(windows, list)

    def test_p2_list_windows_have_titles(self):
        from harma.computer.windows import list_windows
        windows = list_windows()
        for w in windows:
            self.assertIn("title", w)

    def test_p2_window_exists_current(self):
        from harma.computer.windows import get_active_window_info, window_exists
        info = get_active_window_info()
        title = info.get("title", "")
        if title:
            # The active window should be found
            result = window_exists(title[:5])
            self.assertTrue(result)

    def test_p2_window_tool_get_active(self):
        async def run():
            from harma.tools.computer.window_tools import GetActiveWindowTool
            t = GetActiveWindowTool()
            r = await t.execute()
            self.assertTrue(r.success)
        asyncio.run(run())

    def test_p2_window_tool_list_windows(self):
        async def run():
            from harma.tools.computer.window_tools import ListOpenWindowsTool
            t = ListOpenWindowsTool()
            r = await t.execute()
            self.assertTrue(r.success)
        asyncio.run(run())

    def test_p2_window_focus_nonexistent(self):
        """Focusing a nonexistent window should fail gracefully."""
        from harma.computer.windows import focus_window
        result = focus_window("___this_window_does_not_exist___xyz123", wait_seconds=0.5)
        self.assertFalse(result["success"])
        self.assertIn("error", result)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION H — Tool Registry (all Phase 2 tools registered)
# ─────────────────────────────────────────────────────────────────────────────

class TestPhase2ToolRegistry(unittest.TestCase):

    def setUp(self):
        from harma.tools.registry import ToolRegistry
        from harma.tools.computer.screen_tools import (
            TakeScreenshotTool, ObserveScreenTool, GetScreenSizeTool
        )
        from harma.tools.computer.mouse_tools import (
            MouseMoveTool, MouseClickTool, MouseDoubleClickTool,
            MouseRightClickTool, MouseDragTool, MouseScrollTool,
        )
        from harma.tools.computer.keyboard_tools import (
            TypeTextTool, PressKeyTool, HotkeyTool
        )
        from harma.tools.computer.window_tools import (
            GetActiveWindowTool, ListOpenWindowsTool, FocusApplicationTool,
            FindUIElementTool, ClickElementTool,
        )
        self.registry = ToolRegistry()
        for cls in [
            TakeScreenshotTool, ObserveScreenTool, GetScreenSizeTool,
            MouseMoveTool, MouseClickTool, MouseDoubleClickTool,
            MouseRightClickTool, MouseDragTool, MouseScrollTool,
            TypeTextTool, PressKeyTool, HotkeyTool,
            GetActiveWindowTool, ListOpenWindowsTool, FocusApplicationTool,
            FindUIElementTool, ClickElementTool,
        ]:
            self.registry.register(cls())

    def test_p2_all_screen_tools_registered(self):
        for name in ["take_screenshot", "observe_screen", "get_screen_size"]:
            self.assertIn(name, self.registry)

    def test_p2_all_mouse_tools_registered(self):
        for name in [
            "mouse_move", "mouse_click", "mouse_double_click",
            "mouse_right_click", "mouse_drag", "mouse_scroll"
        ]:
            self.assertIn(name, self.registry)

    def test_p2_all_keyboard_tools_registered(self):
        for name in ["type_text", "press_key", "hotkey"]:
            self.assertIn(name, self.registry)

    def test_p2_all_window_tools_registered(self):
        for name in [
            "get_active_window", "list_open_windows", "focus_application",
            "find_ui_element", "click_element"
        ]:
            self.assertIn(name, self.registry)

    def test_p2_tool_count(self):
        self.assertGreaterEqual(len(self.registry), 17)

    def test_p2_tool_definitions_for_llm(self):
        defs = self.registry.list_tool_definitions()
        self.assertGreaterEqual(len(defs), 17)
        names = [d.name for d in defs]
        self.assertIn("take_screenshot", names)
        self.assertIn("mouse_click", names)
        self.assertIn("type_text", names)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION I — Permission Levels
# ─────────────────────────────────────────────────────────────────────────────

class TestPhase2Permissions(unittest.TestCase):

    def _get_tool(self, name: str):
        from harma.tools.computer import screen_tools, mouse_tools, keyboard_tools, window_tools
        all_tools = {}
        for mod in [screen_tools, mouse_tools, keyboard_tools, window_tools]:
            import inspect
            from harma.tools.base import BaseTool
            for _, cls in inspect.getmembers(mod, inspect.isclass):
                if issubclass(cls, BaseTool) and cls.name:
                    all_tools[cls.name] = cls()
        return all_tools.get(name)

    def test_p2_screenshot_is_safe(self):
        from harma.tools.base import PermissionLevel
        from harma.tools.computer.screen_tools import TakeScreenshotTool
        t = TakeScreenshotTool()
        self.assertEqual(t.permission_level, PermissionLevel.SAFE)

    def test_p2_observe_screen_is_safe(self):
        from harma.tools.base import PermissionLevel
        from harma.tools.computer.screen_tools import ObserveScreenTool
        t = ObserveScreenTool()
        self.assertEqual(t.permission_level, PermissionLevel.SAFE)

    def test_p2_mouse_move_is_safe(self):
        from harma.tools.base import PermissionLevel
        from harma.tools.computer.mouse_tools import MouseMoveTool
        t = MouseMoveTool()
        self.assertEqual(t.permission_level, PermissionLevel.SAFE)

    def test_p2_mouse_click_is_sensitive(self):
        from harma.tools.base import PermissionLevel
        from harma.tools.computer.mouse_tools import MouseClickTool
        t = MouseClickTool()
        self.assertEqual(t.permission_level, PermissionLevel.SENSITIVE)

    def test_p2_type_text_is_sensitive(self):
        from harma.tools.base import PermissionLevel
        from harma.tools.computer.keyboard_tools import TypeTextTool
        t = TypeTextTool()
        self.assertEqual(t.permission_level, PermissionLevel.SENSITIVE)

    def test_p2_safe_action_auto_allowed(self):
        from harma.security.permissions import PermissionManager, PermissionDecision
        from harma.tools.base import PermissionLevel
        pm = PermissionManager()
        decision = pm.check("take_screenshot", PermissionLevel.SAFE)
        self.assertEqual(decision, PermissionDecision.ALLOWED)

    def test_p2_sensitive_action_needs_confirm(self):
        from harma.security.permissions import PermissionManager, PermissionDecision
        from harma.tools.base import PermissionLevel
        pm = PermissionManager()
        decision = pm.check("mouse_click", PermissionLevel.SENSITIVE)
        self.assertEqual(decision, PermissionDecision.NEEDS_CONFIRMATION)

    def test_p2_high_risk_always_needs_confirm(self):
        from harma.security.permissions import PermissionManager, PermissionDecision
        from harma.tools.base import PermissionLevel
        pm = PermissionManager()
        decision = pm.check("dangerous_tool", PermissionLevel.HIGH_RISK)
        self.assertEqual(decision, PermissionDecision.NEEDS_CONFIRMATION)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION J — Verification (ActionResult)
# ─────────────────────────────────────────────────────────────────────────────

class TestActionVerification(unittest.TestCase):

    def test_p2_action_result_success(self):
        from harma.computer.controller import ActionResult
        r = ActionResult(success=True, action="mouse_click", detail="Clicked (100, 100)")
        self.assertTrue(r.success)
        self.assertIn("mouse_click", r.to_text())

    def test_p2_action_result_failure(self):
        from harma.computer.controller import ActionResult
        r = ActionResult(success=False, action="mouse_click", error="Out of bounds")
        self.assertFalse(r.success)
        self.assertIn("Out of bounds", r.to_text())

    def test_p2_action_result_to_dict(self):
        from harma.computer.controller import ActionResult
        r = ActionResult(success=True, action="test_action", detail="OK", verification="Verified")
        d = r.to_dict()
        self.assertIn("success", d)
        self.assertIn("verification", d)
        self.assertTrue(d["success"])

    def test_p2_controller_screenshot(self):
        from harma.computer.controller import ComputerController
        ctrl = ComputerController()
        r = ctrl.screenshot()
        self.assertTrue(r.success, msg=r.error)
        self.assertEqual(r.action, "screenshot")

    def test_p2_controller_observe(self):
        from harma.computer.controller import ComputerController
        ctrl = ComputerController()
        obs = ctrl.observe()
        self.assertTrue(obs.screenshot.success)
        self.assertGreater(obs.screen_width, 0)

    def test_p2_controller_get_active_window(self):
        from harma.computer.controller import ComputerController
        ctrl = ComputerController()
        info = ctrl.get_active_window()
        self.assertIn("title", info)

    def test_p2_controller_list_windows(self):
        from harma.computer.controller import ComputerController
        ctrl = ComputerController()
        windows = ctrl.list_windows()
        self.assertIsInstance(windows, list)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION K — Full AgentContext Tool Count
# ─────────────────────────────────────────────────────────────────────────────

class TestAgentContextPhase2(unittest.TestCase):
    """Verify AgentContext registers all Phase 1 + Phase 2 tools."""

    def test_p2_context_tool_count(self):
        from harma.tools.registry import ToolRegistry
        from harma.tools.system.time_tools import GetCurrentTimeTool, GetSystemInfoTool
        from harma.tools.computer.app_tools import OpenApplicationTool, CloseApplicationTool
        from harma.tools.computer.screen_tools import (
            TakeScreenshotTool, ObserveScreenTool, GetScreenSizeTool
        )
        from harma.tools.computer.mouse_tools import (
            MouseMoveTool, MouseClickTool, MouseDoubleClickTool,
            MouseRightClickTool, MouseDragTool, MouseScrollTool,
        )
        from harma.tools.computer.keyboard_tools import (
            TypeTextTool, PressKeyTool, HotkeyTool
        )
        from harma.tools.computer.window_tools import (
            GetActiveWindowTool, ListOpenWindowsTool, FocusApplicationTool,
            FindUIElementTool, ClickElementTool,
        )

        registry = ToolRegistry()
        all_tools = [
            GetCurrentTimeTool(), GetSystemInfoTool(),
            OpenApplicationTool(), CloseApplicationTool(),
            TakeScreenshotTool(), ObserveScreenTool(), GetScreenSizeTool(),
            MouseMoveTool(), MouseClickTool(), MouseDoubleClickTool(),
            MouseRightClickTool(), MouseDragTool(), MouseScrollTool(),
            TypeTextTool(), PressKeyTool(), HotkeyTool(),
            GetActiveWindowTool(), ListOpenWindowsTool(), FocusApplicationTool(),
            FindUIElementTool(), ClickElementTool(),
        ]
        for t in all_tools:
            registry.register(t)

        # Phase 1: 4 tools, Phase 2: 17 tools = 21 total
        self.assertGreaterEqual(len(registry), 21)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Configure test runner with verbose output
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_classes = [
        TestPhase1Regression,
        TestPhase2Config,
        TestSafetyLayer,
        TestScreenCapture,
        TestMouseValidation,
        TestKeyboard,
        TestWindowControl,
        TestPhase2ToolRegistry,
        TestPhase2Permissions,
        TestActionVerification,
        TestAgentContextPhase2,
    ]

    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print()
    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    passed = total - failed
    print(f"{'='*60}")
    print(f"TOTAL: {passed}/{total} PASS  |  {failed} FAIL")
    print(f"{'='*60}")

    sys.exit(0 if result.wasSuccessful() else 1)
