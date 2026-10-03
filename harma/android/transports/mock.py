"""
Harma Fake Android Transport

In-memory, deterministic mock transport for unit testing, offline development,
and CI environments without physical Android hardware.
"""

from __future__ import annotations

import base64
import time
from typing import Any, Optional

from harma.android.exceptions import DeviceLockedError, DeviceNotFoundError
from harma.android.models import (
    AndroidDevice,
    DeviceConnectionState,
    DeviceStatus,
    NotificationItem,
)
from harma.android.transports.base import AndroidTransport

# Minimal 1x1 transparent PNG bytes for mock screenshots
_MOCK_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class FakeAndroidTransport(AndroidTransport):
    """
    Deterministic mock Android device simulator.
    Simulates touch, keyboard, screen hierarchy XML, installed packages,
    settings panels, clipboard, and notifications.
    """

    def __init__(self, devices: list[AndroidDevice] | None = None) -> None:
        self.devices: dict[str, AndroidDevice] = {}
        if devices is not None:
            for d in devices:
                self.devices[d.device_id] = d
        else:
            default_dev = AndroidDevice(
                device_id="emulator-5554",
                model="Pixel 7",
                manufacturer="Google",
                android_version="14",
                screen_width=1080,
                screen_height=2400,
                state=DeviceConnectionState.CONNECTED,
                is_emulator=True,
                is_locked=False,
            )
            self.devices[default_dev.device_id] = default_dev

        self.active_device_id: Optional[str] = (
            next(iter(self.devices.keys())) if self.devices else None
        )

        # Device state per device_id
        self.battery_levels: dict[str, int] = {d_id: 88 for d_id in self.devices}
        self.charging_states: dict[str, bool] = {d_id: True for d_id in self.devices}
        self.current_apps: dict[str, tuple[str, str]] = {
            d_id: ("com.android.launcher", "com.android.launcher3.uioverrides.QuickstepLauncher")
            for d_id in self.devices
        }
        self.wifi_states: dict[str, bool] = {d_id: True for d_id in self.devices}
        self.bluetooth_states: dict[str, bool] = {d_id: False for d_id in self.devices}
        self.flashlight_states: dict[str, bool] = {d_id: False for d_id in self.devices}
        self.mobile_data_states: dict[str, bool] = {d_id: False for d_id in self.devices}
        self.volume_levels: dict[str, int] = {d_id: 50 for d_id in self.devices}
        self.screen_on_states: dict[str, bool] = {d_id: True for d_id in self.devices}
        self.location_states: dict[str, bool] = {d_id: True for d_id in self.devices}
        self.clipboards: dict[str, str] = {d_id: "" for d_id in self.devices}
        self.notifications: dict[str, list[NotificationItem]] = {
            d_id: [
                NotificationItem(
                    id="notif_1",
                    package="com.whatsapp",
                    app_name="WhatsApp",
                    title="Mom",
                    text="Dinner is ready!",
                    timestamp=time.time() - 300,
                ),
                NotificationItem(
                    id="notif_2",
                    package="com.google.android.gm",
                    app_name="Gmail",
                    title="Security alert",
                    text="New login from Windows PC",
                    timestamp=time.time() - 600,
                ),
            ]
            for d_id in self.devices
        }

        # Installed packages simulation
        self.installed_packages: list[str] = [
            "com.android.settings",
            "com.android.chrome",
            "com.whatsapp",
            "com.google.android.youtube",
            "com.google.android.calculator",
            "com.google.android.apps.maps",
            "com.google.android.gm",
            "com.google.android.dialer",
            "com.google.android.apps.messaging",
            "com.google.android.apps.photos",
            "com.android.camera2",
            "com.android.launcher",
        ]

        # Action history log for test verification
        self.action_history: list[dict[str, Any]] = []

        # Custom screen hierarchy overrides: screen_key -> XML string
        self.custom_hierarchies: dict[str, str] = {}

        # Screen input buffer / typed text
        self.typed_text: str = ""

    def _ensure_device(self, device_id: Optional[str]) -> str:
        d_id = device_id or self.active_device_id
        if not d_id or d_id not in self.devices:
            raise DeviceNotFoundError(f"Device '{d_id}' not found.")
        dev = self.devices[d_id]
        if dev.state != DeviceConnectionState.CONNECTED:
            raise DeviceNotFoundError(f"Device '{d_id}' is disconnected.")
        return d_id

    async def list_devices(self) -> list[AndroidDevice]:
        return list(self.devices.values())

    async def connect(self, device_id: Optional[str] = None) -> AndroidDevice:
        if device_id:
            if device_id not in self.devices:
                raise DeviceNotFoundError(f"Device '{device_id}' not found.")
            self.active_device_id = device_id
        elif not self.active_device_id and self.devices:
            self.active_device_id = next(iter(self.devices.keys()))

        if not self.active_device_id:
            raise DeviceNotFoundError("No Android devices available to connect.")

        dev = self.devices[self.active_device_id]
        dev.state = DeviceConnectionState.CONNECTED
        self.action_history.append({"action": "connect", "device_id": self.active_device_id})
        return dev

    async def disconnect(self, device_id: Optional[str] = None) -> bool:
        d_id = self._ensure_device(device_id)
        self.devices[d_id].state = DeviceConnectionState.DISCONNECTED
        self.action_history.append({"action": "disconnect", "device_id": d_id})
        if self.active_device_id == d_id:
            self.active_device_id = None
        return True

    async def get_device_info(self, device_id: str) -> dict[str, Any]:
        d_id = self._ensure_device(device_id)
        dev = self.devices[d_id]
        return {
            "device_id": dev.device_id,
            "model": dev.model,
            "manufacturer": dev.manufacturer,
            "android_version": dev.android_version,
            "screen_width": dev.screen_width,
            "screen_height": dev.screen_height,
            "is_emulator": dev.is_emulator,
        }

    async def get_device_status(self, device_id: str) -> DeviceStatus:
        d_id = self._ensure_device(device_id)
        dev = self.devices[d_id]
        pkg, act = self.current_apps.get(d_id, ("com.android.launcher", "QuickstepLauncher"))
        return DeviceStatus(
            device_id=dev.device_id,
            manufacturer=dev.manufacturer,
            model=dev.model,
            android_version=dev.android_version,
            screen_size=(dev.screen_width, dev.screen_height),
            connection_state=dev.state.value,
            battery_level=self.battery_levels.get(d_id, 88),
            is_charging=self.charging_states.get(d_id, True),
            is_locked=dev.is_locked,
            current_package=pkg,
            current_activity=act,
            wifi_enabled=self.wifi_states.get(d_id, True),
            bluetooth_enabled=self.bluetooth_states.get(d_id, False),
            flashlight_on=self.flashlight_states.get(d_id, False),
            mobile_data_enabled=self.mobile_data_states.get(d_id, False),
            volume_level=self.volume_levels.get(d_id, 50),
            screen_on=self.screen_on_states.get(d_id, True),
            location_enabled=self.location_states.get(d_id, True),
            network_state="wifi" if self.wifi_states.get(d_id, True) else ("mobile" if self.mobile_data_states.get(d_id, False) else "none"),
        )

    async def capture_screenshot(self, device_id: str) -> bytes:
        d_id = self._ensure_device(device_id)
        self.action_history.append({"action": "screenshot", "device_id": d_id})
        return _MOCK_PNG_BYTES

    async def get_ui_hierarchy(self, device_id: str) -> str:
        d_id = self._ensure_device(device_id)
        pkg, _ = self.current_apps.get(d_id, ("com.android.launcher", ""))

        if pkg in self.custom_hierarchies:
            return self.custom_hierarchies[pkg]

        # Generate hierarchy based on current app
        return self._generate_screen_xml(d_id, pkg)

    def _generate_screen_xml(self, device_id: str, package: str) -> str:
        wifi_state_str = "ON" if self.wifi_states.get(device_id, True) else "OFF"
        wifi_checked = "true" if self.wifi_states.get(device_id, True) else "false"

        if package == "com.android.settings":
            return f"""<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.android.settings" bounds="[0,0][1080,2400]">
    <node index="0" text="Settings" resource-id="com.android.settings:id/settings_title" class="android.widget.TextView" package="com.android.settings" bounds="[60,120][1020,240]" clickable="false" enabled="true" />
    <node index="1" text="Search settings" resource-id="com.android.settings:id/search_action_bar" class="android.widget.EditText" package="com.android.settings" bounds="[60,260][1020,380]" clickable="true" enabled="true" />
    <node index="2" text="Network &amp; internet" resource-id="com.android.settings:id/network_settings" class="android.widget.TextView" content-desc="Network and internet settings" package="com.android.settings" bounds="[60,400][1020,520]" clickable="true" enabled="true" />
    <node index="3" text="Wi-Fi" resource-id="com.android.settings:id/wifi_settings" class="android.widget.TextView" content-desc="Wi-Fi settings" package="com.android.settings" bounds="[60,540][850,660]" clickable="true" enabled="true" />
    <node index="4" text="{wifi_state_str}" resource-id="com.android.settings:id/wifi_switch" class="android.widget.Switch" content-desc="Wi-Fi toggle switch" package="com.android.settings" bounds="[860,540][1020,660]" clickable="true" enabled="true" checkable="true" checked="{wifi_checked}" />
    <node index="5" text="Connected devices" resource-id="com.android.settings:id/bluetooth_settings" class="android.widget.TextView" content-desc="Bluetooth and USB settings" package="com.android.settings" bounds="[60,680][1020,800]" clickable="true" enabled="true" />
    <node index="6" text="Apps" resource-id="com.android.settings:id/apps_settings" class="android.widget.TextView" package="com.android.settings" bounds="[60,820][1020,940]" clickable="true" enabled="true" />
    <node index="7" text="Battery" resource-id="com.android.settings:id/battery_settings" class="android.widget.TextView" package="com.android.settings" bounds="[60,960][1020,1080]" clickable="true" enabled="true" />
    <node index="8" text="Display" resource-id="com.android.settings:id/display_settings" class="android.widget.TextView" package="com.android.settings" bounds="[60,1100][1020,1220]" clickable="true" enabled="true" />
  </node>
</hierarchy>"""

        elif package == "com.android.chrome":
            url_text = self.typed_text or "Search or type URL"
            return f"""<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.android.chrome" bounds="[0,0][1080,2400]">
    <node index="0" text="{url_text}" resource-id="com.android.chrome:id/url_bar" class="android.widget.EditText" content-desc="Search or type web address" package="com.android.chrome" bounds="[40,100][950,220]" clickable="true" enabled="true" />
    <node index="1" text="" resource-id="com.android.chrome:id/tab_switcher_button" class="android.widget.ImageButton" content-desc="Switch tabs" package="com.android.chrome" bounds="[960,100][1060,220]" clickable="true" enabled="true" />
    <node index="2" text="Google" resource-id="com.android.chrome:id/search_logo" class="android.widget.ImageView" package="com.android.chrome" bounds="[390,400][690,550]" clickable="false" enabled="true" />
    <node index="3" text="Search with Google" resource-id="com.android.chrome:id/search_box" class="android.widget.TextView" package="com.android.chrome" bounds="[80,600][1000,720]" clickable="true" enabled="true" />
  </node>
</hierarchy>"""

        elif package == "com.whatsapp":
            return """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.whatsapp" bounds="[0,0][1080,2400]">
    <node index="0" text="WhatsApp" resource-id="com.whatsapp:id/toolbar_title" class="android.widget.TextView" package="com.whatsapp" bounds="[50,100][400,200]" clickable="false" enabled="true" />
    <node index="1" text="Search" resource-id="com.whatsapp:id/menuitem_search" class="android.widget.TextView" content-desc="Search chats" package="com.whatsapp" bounds="[800,100][920,200]" clickable="true" enabled="true" />
    <node index="2" text="Chats" resource-id="com.whatsapp:id/tab_chats" class="android.widget.TextView" package="com.whatsapp" bounds="[50,220][300,320]" clickable="true" enabled="true" selected="true" />
    <node index="3" text="Updates" resource-id="com.whatsapp:id/tab_updates" class="android.widget.TextView" package="com.whatsapp" bounds="[350,220][600,320]" clickable="true" enabled="true" />
    <node index="4" text="Calls" resource-id="com.whatsapp:id/tab_calls" class="android.widget.TextView" package="com.whatsapp" bounds="[650,220][900,320]" clickable="true" enabled="true" />
    <node index="5" text="Alice" resource-id="com.whatsapp:id/conversations_row_contact_name" class="android.widget.TextView" package="com.whatsapp" bounds="[150,350][800,430]" clickable="true" enabled="true" />
    <node index="6" text="Bob" resource-id="com.whatsapp:id/conversations_row_contact_name" class="android.widget.TextView" package="com.whatsapp" bounds="[150,450][800,530]" clickable="true" enabled="true" />
  </node>
</hierarchy>"""

        elif package == "com.google.android.youtube":
            return """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.google.android.youtube" bounds="[0,0][1080,2400]">
    <node index="0" text="YouTube" resource-id="com.google.android.youtube:id/youtube_logo" class="android.widget.ImageView" package="com.google.android.youtube" bounds="[50,100][300,200]" clickable="false" enabled="true" />
    <node index="1" text="Search" resource-id="com.google.android.youtube:id/menu_item_search" class="android.widget.ImageView" content-desc="Search YouTube" package="com.google.android.youtube" bounds="[850,100][950,200]" clickable="true" enabled="true" />
    <node index="2" text="Explore" resource-id="com.google.android.youtube:id/explore" class="android.widget.Button" package="com.google.android.youtube" bounds="[50,220][300,300]" clickable="true" enabled="true" />
    <node index="3" text="AI Agents in 2026 - Complete Guide" resource-id="com.google.android.youtube:id/video_title" class="android.widget.TextView" package="com.google.android.youtube" bounds="[50,400][1030,550]" clickable="true" enabled="true" />
  </node>
</hierarchy>"""

        elif package == "com.google.android.calculator":
            return """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.google.android.calculator" bounds="[0,0][1080,2400]">
    <node index="0" text="0" resource-id="com.google.android.calculator:id/result_final" class="android.widget.TextView" package="com.google.android.calculator" bounds="[60,300][1020,500]" clickable="false" enabled="true" />
    <node index="1" text="7" resource-id="com.google.android.calculator:id/digit_7" class="android.widget.Button" package="com.google.android.calculator" bounds="[60,800][260,1000]" clickable="true" enabled="true" />
    <node index="2" text="8" resource-id="com.google.android.calculator:id/digit_8" class="android.widget.Button" package="com.google.android.calculator" bounds="[300,800][500,1000]" clickable="true" enabled="true" />
    <node index="3" text="9" resource-id="com.google.android.calculator:id/digit_9" class="android.widget.Button" package="com.google.android.calculator" bounds="[540,800][740,1000]" clickable="true" enabled="true" />
    <node index="4" text="×" resource-id="com.google.android.calculator:id/op_mul" class="android.widget.Button" content-desc="multiply" package="com.google.android.calculator" bounds="[780,800][980,1000]" clickable="true" enabled="true" />
    <node index="5" text="=" resource-id="com.google.android.calculator:id/eq" class="android.widget.Button" content-desc="equals" package="com.google.android.calculator" bounds="[780,1400][980,1600]" clickable="true" enabled="true" />
  </node>
</hierarchy>"""

        else:
            # Default Home / Launcher screen
            return """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.android.launcher" bounds="[0,0][1080,2400]">
    <node index="0" text="Google Search" resource-id="com.google.android.googlequicksearchbox:id/g_search_box" class="android.widget.TextView" content-desc="Search" package="com.android.launcher" bounds="[60,200][1020,320]" clickable="true" enabled="true" />
    <node index="1" text="Phone" resource-id="com.google.android.dialer:id/icon" class="android.widget.TextView" content-desc="Phone" package="com.android.launcher" bounds="[60,2100][240,2280]" clickable="true" enabled="true" />
    <node index="2" text="Messages" resource-id="com.google.android.apps.messaging:id/icon" class="android.widget.TextView" content-desc="Messages" package="com.android.launcher" bounds="[300,2100][480,2280]" clickable="true" enabled="true" />
    <node index="3" text="Chrome" resource-id="com.android.chrome:id/icon" class="android.widget.TextView" content-desc="Chrome browser" package="com.android.launcher" bounds="[540,2100][720,2280]" clickable="true" enabled="true" />
    <node index="4" text="Camera" resource-id="com.android.camera2:id/icon" class="android.widget.TextView" content-desc="Camera" package="com.android.launcher" bounds="[780,2100][960,2280]" clickable="true" enabled="true" />
  </node>
</hierarchy>"""

    async def tap(self, device_id: str, x: int, y: int) -> bool:
        d_id = self._ensure_device(device_id)
        if self.devices[d_id].is_locked:
            raise DeviceLockedError()

        self.action_history.append({"action": "tap", "device_id": d_id, "x": x, "y": y})

        # Simulate toggle interaction on Wi-Fi switch if clicked near bounds [860,540][1020,660]
        pkg, _ = self.current_apps.get(d_id, ("", ""))
        if pkg == "com.android.settings" and (860 <= x <= 1020 and 540 <= y <= 660):
            self.wifi_states[d_id] = not self.wifi_states.get(d_id, True)

        return True

    async def long_press(self, device_id: str, x: int, y: int, duration_ms: int = 1000) -> bool:
        d_id = self._ensure_device(device_id)
        if self.devices[d_id].is_locked:
            raise DeviceLockedError()
        self.action_history.append(
            {"action": "long_press", "device_id": d_id, "x": x, "y": y, "duration_ms": duration_ms}
        )
        return True

    async def double_tap(self, device_id: str, x: int, y: int) -> bool:
        d_id = self._ensure_device(device_id)
        if self.devices[d_id].is_locked:
            raise DeviceLockedError()
        self.action_history.append({"action": "double_tap", "device_id": d_id, "x": x, "y": y})
        return True

    async def swipe(
        self, device_id: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300
    ) -> bool:
        d_id = self._ensure_device(device_id)
        if self.devices[d_id].is_locked:
            raise DeviceLockedError()
        self.action_history.append(
            {
                "action": "swipe",
                "device_id": d_id,
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "duration_ms": duration_ms,
            }
        )
        return True

    async def drag(
        self, device_id: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 800
    ) -> bool:
        d_id = self._ensure_device(device_id)
        if self.devices[d_id].is_locked:
            raise DeviceLockedError()
        self.action_history.append(
            {
                "action": "drag",
                "device_id": d_id,
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "duration_ms": duration_ms,
            }
        )
        return True

    async def type_text(self, device_id: str, text: str) -> bool:
        d_id = self._ensure_device(device_id)
        if self.devices[d_id].is_locked:
            raise DeviceLockedError()
        self.typed_text = text
        self.action_history.append({"action": "type_text", "device_id": d_id, "text": text})
        return True

    async def press_key(self, device_id: str, key_code: str | int) -> bool:
        d_id = self._ensure_device(device_id)
        kc_str = str(key_code).upper()
        self.action_history.append({"action": "press_key", "device_id": d_id, "key": kc_str})

        if "BACK" in kc_str or kc_str == "4":
            # Go back or to launcher
            pkg, _ = self.current_apps.get(d_id, ("", ""))
            if pkg != "com.android.launcher":
                self.current_apps[d_id] = ("com.android.launcher", "QuickstepLauncher")
        elif "HOME" in kc_str or kc_str == "3":
            self.current_apps[d_id] = ("com.android.launcher", "QuickstepLauncher")
        elif "APP_SWITCH" in kc_str or kc_str == "187":
            pass

        return True

    async def list_packages(self, device_id: str) -> list[str]:
        self._ensure_device(device_id)
        return list(self.installed_packages)

    async def get_current_app(self, device_id: str) -> tuple[str, str]:
        d_id = self._ensure_device(device_id)
        return self.current_apps.get(
            d_id, ("com.android.launcher", "com.android.launcher3.uioverrides.QuickstepLauncher")
        )

    async def launch_app(self, device_id: str, package: str) -> bool:
        d_id = self._ensure_device(device_id)
        if self.devices[d_id].is_locked:
            raise DeviceLockedError()

        if package not in self.installed_packages:
            return False

        activity = f"{package}.MainActivity"
        if package == "com.android.settings":
            activity = "com.android.settings.Settings"
        elif package == "com.android.chrome":
            activity = "com.google.android.apps.chrome.Main"

        self.current_apps[d_id] = (package, activity)
        self.action_history.append({"action": "launch_app", "device_id": d_id, "package": package})
        return True

    async def close_app(self, device_id: str, package: str) -> bool:
        d_id = self._ensure_device(device_id)
        self.action_history.append({"action": "close_app", "device_id": d_id, "package": package})
        cur_pkg, _ = self.current_apps.get(d_id, ("", ""))
        if cur_pkg == package:
            self.current_apps[d_id] = ("com.android.launcher", "QuickstepLauncher")
        return True

    async def get_clipboard(self, device_id: str) -> str:
        d_id = self._ensure_device(device_id)
        return self.clipboards.get(d_id, "")

    async def set_clipboard(self, device_id: str, text: str) -> bool:
        d_id = self._ensure_device(device_id)
        self.clipboards[d_id] = text
        self.action_history.append({"action": "set_clipboard", "device_id": d_id})
        return True

    async def get_notifications(self, device_id: str) -> list[NotificationItem]:
        d_id = self._ensure_device(device_id)
        return list(self.notifications.get(d_id, []))

    async def open_settings(self, device_id: str, panel: str = "general") -> bool:
        d_id = self._ensure_device(device_id)
        if self.devices[d_id].is_locked:
            raise DeviceLockedError()
        self.current_apps[d_id] = ("com.android.settings", "com.android.settings.Settings")
        self.action_history.append({"action": "open_settings", "device_id": d_id, "panel": panel})
        return True

    async def is_locked(self, device_id: str) -> bool:
        d_id = self._ensure_device(device_id)
        return self.devices[d_id].is_locked

    async def set_flashlight(self, device_id: str, enabled: bool) -> bool:
        d_id = self._ensure_device(device_id)
        self.flashlight_states[d_id] = bool(enabled)
        self.action_history.append({"action": "set_flashlight", "device_id": d_id, "enabled": enabled})
        return True

    async def get_flashlight(self, device_id: str) -> bool:
        d_id = self._ensure_device(device_id)
        return self.flashlight_states.get(d_id, False)

    async def set_wifi(self, device_id: str, enabled: bool) -> tuple[bool, str]:
        d_id = self._ensure_device(device_id)
        self.wifi_states[d_id] = bool(enabled)
        self.action_history.append({"action": "set_wifi", "device_id": d_id, "enabled": enabled})
        return True, f"Wi-Fi {'enabled' if enabled else 'disabled'} successfully."

    async def get_wifi(self, device_id: str) -> bool:
        d_id = self._ensure_device(device_id)
        return self.wifi_states.get(d_id, True)

    async def set_mobile_data(self, device_id: str, enabled: bool) -> tuple[bool, str]:
        d_id = self._ensure_device(device_id)
        # Spec §17: Android requires MODIFY_PHONE_STATE or carrier privileges.
        # Fallback to Internet Settings Panel without falsely reporting direct modification.
        self.action_history.append({"action": "set_mobile_data", "device_id": d_id, "enabled": enabled})
        self.current_apps[d_id] = ("com.android.settings", "Settings$NetworkDashboardActivity")
        return False, "settings_panel"

    async def get_mobile_data(self, device_id: str) -> bool:
        d_id = self._ensure_device(device_id)
        return self.mobile_data_states.get(d_id, False)

    async def set_bluetooth(self, device_id: str, enabled: bool) -> tuple[bool, str]:
        d_id = self._ensure_device(device_id)
        self.bluetooth_states[d_id] = bool(enabled)
        self.action_history.append({"action": "set_bluetooth", "device_id": d_id, "enabled": enabled})
        return True, f"Bluetooth {'enabled' if enabled else 'disabled'}."

    async def get_bluetooth(self, device_id: str) -> bool:
        d_id = self._ensure_device(device_id)
        return self.bluetooth_states.get(d_id, False)

    async def set_volume(self, device_id: str, level: int, stream: str = "media") -> int:
        d_id = self._ensure_device(device_id)
        clamped = max(0, min(100, int(level)))
        self.volume_levels[d_id] = clamped
        self.action_history.append({"action": "set_volume", "device_id": d_id, "level": clamped, "stream": stream})
        return clamped

    async def get_volume(self, device_id: str, stream: str = "media") -> int:
        d_id = self._ensure_device(device_id)
        return self.volume_levels.get(d_id, 50)

    async def navigate(self, device_id: str, destination: str) -> bool:
        d_id = self._ensure_device(device_id)
        self.current_apps[d_id] = ("com.google.android.apps.maps", "com.google.android.maps.MapsActivity")
        self.action_history.append({"action": "navigate", "device_id": d_id, "destination": destination})
        return True

    async def open_camera(self, device_id: str) -> bool:
        d_id = self._ensure_device(device_id)
        self.current_apps[d_id] = ("com.android.camera2", "com.android.camera.CameraLauncher")
        self.action_history.append({"action": "open_camera", "device_id": d_id})
        return True

    def lock_device(self, device_id: Optional[str] = None) -> bool:
        d_id = device_id or self.active_device_id
        if d_id and d_id in self.devices:
            self.devices[d_id].is_locked = True
            self.screen_on_states[d_id] = False
            self.action_history.append({"action": "lock", "device_id": d_id})
        return True

    def unlock_device(self, device_id: Optional[str] = None) -> bool:
        d_id = device_id or self.active_device_id
        if d_id and d_id in self.devices:
            self.devices[d_id].is_locked = False
            self.screen_on_states[d_id] = True
            self.action_history.append({"action": "unlock", "device_id": d_id})
        return True
