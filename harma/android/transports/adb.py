"""
Harma ADB Android Transport

Production transport interacting with Android devices via the Android Debug Bridge (ADB).
Supports USB and Wi-Fi connected physical devices and Android emulators.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from typing import Any, Optional

from harma.android.exceptions import (
    DeviceLockedError,
    DeviceNotFoundError,
    TransportError,
)
from harma.android.models import (
    AndroidDevice,
    DeviceConnectionState,
    DeviceStatus,
    NotificationItem,
)
from harma.android.transports.base import AndroidTransport
from harma.config.logging_config import get_logger

log = get_logger(__name__)


class ADBTransport(AndroidTransport):
    """
    Direct ADB subprocess transport.
    """

    def __init__(self, adb_path: str = "adb") -> None:
        self.adb_path = adb_path
        self.active_device_id: Optional[str] = None
        self._is_adb_available: Optional[bool] = None

    def check_adb_available(self) -> bool:
        """Check if adb binary is available on the system."""
        if self._is_adb_available is not None:
            return self._is_adb_available
        found = shutil.which(self.adb_path) is not None or os.path.exists(self.adb_path)
        self._is_adb_available = found
        return found

    def _ensure_adb(self) -> None:
        if not self.check_adb_available():
            raise TransportError(
                f"ADB binary '{self.adb_path}' not found in PATH. "
                "Install Android SDK Platform Tools or specify the full path in config."
            )

    async def _run_cmd(
        self, args: list[str], device_id: Optional[str] = None, timeout: float = 15.0
    ) -> str:
        """Execute an ADB command asynchronously."""
        self._ensure_adb()
        cmd = [self.adb_path]
        target_id = device_id or self.active_device_id
        if target_id:
            cmd.extend(["-s", target_id])
        cmd.extend(args)

        log.debug("Executing ADB: %s", " ".join(cmd))
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out_str = stdout.decode("utf-8", errors="replace").strip()
            err_str = stderr.decode("utf-8", errors="replace").strip()

            if proc.returncode != 0:
                log.warning("ADB command %s returned %d: %s", cmd, proc.returncode, err_str)
                raise TransportError(f"ADB error ({proc.returncode}): {err_str or out_str}")

            return out_str
        except asyncio.TimeoutError:
            raise TransportError(f"ADB command timed out after {timeout}s: {' '.join(cmd)}")
        except Exception as exc:
            if isinstance(exc, TransportError):
                raise
            raise TransportError(f"Failed to execute ADB command: {exc}")

    async def _run_shell(
        self, shell_cmd: str, device_id: Optional[str] = None, timeout: float = 15.0
    ) -> str:
        """Execute an ADB shell command."""
        return await self._run_cmd(["shell", shell_cmd], device_id=device_id, timeout=timeout)

    async def list_devices(self) -> list[AndroidDevice]:
        """List devices via `adb devices -l`."""
        if not self.check_adb_available():
            return []

        out = await self._run_cmd(["devices", "-l"], device_id=None)
        devices: list[AndroidDevice] = []

        for line in out.splitlines()[1:]:  # skip header "List of devices attached"
            line = line.strip()
            if not line:
                continue

            parts = line.split()
            device_id = parts[0]
            status_str = parts[1] if len(parts) > 1 else "unknown"

            state = DeviceConnectionState.UNKNOWN
            if status_str == "device":
                state = DeviceConnectionState.CONNECTED
            elif status_str == "unauthorized":
                state = DeviceConnectionState.UNAUTHORIZED
            elif status_str == "offline":
                state = DeviceConnectionState.OFFLINE
            elif status_str == "recovery":
                state = DeviceConnectionState.RECOVERY

            model = "Android"
            manufacturer = "Unknown"
            for p in parts[2:]:
                if p.startswith("model:"):
                    model = p.split(":", 1)[1]
                elif p.startswith("device:"):
                    manufacturer = p.split(":", 1)[1]

            is_emu = "emulator" in device_id or "127.0.0.1" in device_id or "localhost" in device_id

            dev = AndroidDevice(
                device_id=device_id,
                model=model,
                manufacturer=manufacturer,
                state=state,
                is_emulator=is_emu,
            )
            devices.append(dev)

        return devices

    async def connect(self, device_id: Optional[str] = None) -> AndroidDevice:
        devices = await self.list_devices()
        connected = [d for d in devices if d.state == DeviceConnectionState.CONNECTED]

        if not connected:
            raise DeviceNotFoundError("No authorized Android devices currently connected via ADB.")

        if device_id:
            match = next((d for d in connected if d.device_id == device_id), None)
            if not match:
                raise DeviceNotFoundError(f"Device '{device_id}' is not connected or unauthorized.")
            target = match
        else:
            target = connected[0]

        self.active_device_id = target.device_id
        # Populate detailed info
        try:
            info = await self.get_device_info(target.device_id)
            target.model = info.get("model", target.model)
            target.manufacturer = info.get("manufacturer", target.manufacturer)
            target.android_version = info.get("android_version", "Unknown")
            target.screen_width = info.get("screen_width", 1080)
            target.screen_height = info.get("screen_height", 2400)
        except Exception as exc:
            log.warning("Could not fetch full device info for %s: %s", target.device_id, exc)

        return target

    async def disconnect(self, device_id: Optional[str] = None) -> bool:
        target_id = device_id or self.active_device_id
        if self.active_device_id == target_id:
            self.active_device_id = None
        return True

    async def get_device_info(self, device_id: str) -> dict[str, Any]:
        info: dict[str, Any] = {"device_id": device_id}
        try:
            mfr = await self._run_shell("getprop ro.product.manufacturer", device_id=device_id)
            model = await self._run_shell("getprop ro.product.model", device_id=device_id)
            version = await self._run_shell(
                "getprop ro.build.version.release", device_id=device_id
            )
            wm_size = await self._run_shell("wm size", device_id=device_id)

            info["manufacturer"] = mfr
            info["model"] = model
            info["android_version"] = version

            # Parse wm size: Physical size: 1080x2400
            m = re.search(r"(\d+)x(\d+)", wm_size)
            if m:
                info["screen_width"] = int(m.group(1))
                info["screen_height"] = int(m.group(2))
            else:
                info["screen_width"] = 1080
                info["screen_height"] = 2400
        except Exception as exc:
            log.warning("Error fetching device info: %s", exc)

        return info

    async def get_device_status(self, device_id: str) -> DeviceStatus:
        info = await self.get_device_info(device_id)
        w = info.get("screen_width", 1080)
        h = info.get("screen_height", 2400)

        # Battery
        battery_level = 100
        is_charging = False
        try:
            dumpsys_batt = await self._run_shell("dumpsys battery", device_id=device_id)
            for line in dumpsys_batt.splitlines():
                if "level:" in line:
                    battery_level = int(line.split(":")[1].strip())
                elif "AC powered:" in line or "USB powered:" in line:
                    if "true" in line.lower():
                        is_charging = True
        except Exception:
            pass

        # Current app
        pkg, act = await self.get_current_app(device_id)
        locked = await self.is_locked(device_id)

        return DeviceStatus(
            device_id=device_id,
            manufacturer=info.get("manufacturer", "Unknown"),
            model=info.get("model", "Unknown"),
            android_version=info.get("android_version", "Unknown"),
            screen_size=(w, h),
            connection_state="connected",
            battery_level=battery_level,
            is_charging=is_charging,
            is_locked=locked,
            current_package=pkg,
            current_activity=act,
        )

    async def capture_screenshot(self, device_id: str) -> bytes:
        """Capture screenshot directly via `exec-out screencap -p`."""
        self._ensure_adb()
        cmd = [self.adb_path, "-s", device_id, "exec-out", "screencap", "-p"]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise TransportError(f"Failed to capture screenshot: {stderr.decode('utf-8', errors='replace')}")
        return stdout

    async def get_ui_hierarchy(self, device_id: str) -> str:
        """Dump UI hierarchy via `uiautomator dump`."""
        tmp_path = "/data/local/tmp/uidump.xml"
        await self._run_shell(f"uiautomator dump {tmp_path}", device_id=device_id)
        xml_content = await self._run_shell(f"cat {tmp_path}", device_id=device_id)
        return xml_content

    async def tap(self, device_id: str, x: int, y: int) -> bool:
        if await self.is_locked(device_id):
            raise DeviceLockedError()
        await self._run_shell(f"input tap {x} {y}", device_id=device_id)
        return True

    async def long_press(self, device_id: str, x: int, y: int, duration_ms: int = 1000) -> bool:
        if await self.is_locked(device_id):
            raise DeviceLockedError()
        await self._run_shell(
            f"input swipe {x} {y} {x} {y} {duration_ms}", device_id=device_id
        )
        return True

    async def double_tap(self, device_id: str, x: int, y: int) -> bool:
        await self.tap(device_id, x, y)
        await asyncio.sleep(0.1)
        await self.tap(device_id, x, y)
        return True

    async def swipe(
        self, device_id: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300
    ) -> bool:
        if await self.is_locked(device_id):
            raise DeviceLockedError()
        await self._run_shell(
            f"input swipe {x1} {y1} {x2} {y2} {duration_ms}", device_id=device_id
        )
        return True

    async def drag(
        self, device_id: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 800
    ) -> bool:
        return await self.swipe(device_id, x1, y1, x2, y2, duration_ms)

    async def type_text(self, device_id: str, text: str) -> bool:
        if await self.is_locked(device_id):
            raise DeviceLockedError()
        # Escape special characters for ADB input text
        safe_text = re.sub(r'([\\&|;()<>`"\'*?~% ])', r"\\\1", text)
        await self._run_shell(f"input text {safe_text}", device_id=device_id)
        return True

    async def press_key(self, device_id: str, key_code: str | int) -> bool:
        await self._run_shell(f"input keyevent {key_code}", device_id=device_id)
        return True

    async def list_packages(self, device_id: str) -> list[str]:
        out = await self._run_shell("pm list packages", device_id=device_id)
        packages = []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                packages.append(line.split("package:", 1)[1].strip())
        return packages

    async def get_current_app(self, device_id: str) -> tuple[str, str]:
        """Extract focused package and activity from dumpsys window."""
        try:
            out = await self._run_shell(
                "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'", device_id=device_id
            )
            # Example: mCurrentFocus=Window{... u0 com.android.settings/com.android.settings.Settings}
            match = re.search(r"([a-zA-Z0-9._]+)/([a-zA-Z0-9._]+)", out)
            if match:
                return (match.group(1), match.group(2))
        except Exception:
            pass
        return ("unknown", "unknown")

    async def launch_app(self, device_id: str, package: str) -> bool:
        if await self.is_locked(device_id):
            raise DeviceLockedError()
        # Use monkey to start the default launcher intent
        res = await self._run_shell(
            f"monkey -p {package} -c android.intent.category.LAUNCHER 1", device_id=device_id
        )
        return "Events injected: 1" in res or "No activities found" not in res

    async def close_app(self, device_id: str, package: str) -> bool:
        await self._run_shell(f"am force-stop {package}", device_id=device_id)
        return True

    async def get_clipboard(self, device_id: str) -> str:
        try:
            out = await self._run_shell("cmd clipboard get", device_id=device_id)
            return out
        except Exception:
            return ""

    async def set_clipboard(self, device_id: str, text: str) -> bool:
        try:
            safe = re.sub(r'([\\&|;()<>`"\'*?~% ])', r"\\\1", text)
            await self._run_shell(f"cmd clipboard set {safe}", device_id=device_id)
            return True
        except Exception:
            return False

    async def get_notifications(self, device_id: str) -> list[NotificationItem]:
        items: list[NotificationItem] = []
        try:
            out = await self._run_shell(
                "dumpsys notification --noredact | grep -E 'pkg=|android.title|android.text'",
                device_id=device_id,
            )
            cur_pkg = ""
            cur_title = ""
            cur_text = ""
            idx = 0
            for line in out.splitlines():
                if "pkg=" in line:
                    m = re.search(r"pkg=([a-zA-Z0-9._]+)", line)
                    if m:
                        cur_pkg = m.group(1)
                elif "android.title=" in line:
                    cur_title = line.split("android.title=", 1)[1].strip()
                elif "android.text=" in line:
                    cur_text = line.split("android.text=", 1)[1].strip()
                    if cur_pkg and (cur_title or cur_text):
                        idx += 1
                        items.append(
                            NotificationItem(
                                id=f"notif_{idx}",
                                package=cur_pkg,
                                title=cur_title,
                                text=cur_text,
                            )
                        )
                        cur_pkg = ""
                        cur_title = ""
                        cur_text = ""
        except Exception as exc:
            log.warning("Could not read notifications via dumpsys: %s", exc)
        return items

    async def open_settings(self, device_id: str, panel: str = "general") -> bool:
        if await self.is_locked(device_id):
            raise DeviceLockedError()
        action_map = {
            "general": "android.settings.SETTINGS",
            "wifi": "android.settings.WIFI_SETTINGS",
            "bluetooth": "android.settings.BLUETOOTH_SETTINGS",
            "display": "android.settings.DISPLAY_SETTINGS",
            "sound": "android.settings.SOUND_SETTINGS",
        }
        action = action_map.get(panel.lower(), "android.settings.SETTINGS")
        await self._run_shell(f"am start -a {action}", device_id=device_id)
        return True

    async def is_locked(self, device_id: str) -> bool:
        try:
            out = await self._run_shell(
                "dumpsys window | grep -E 'mShowingLockscreen|isStatusBarKeyguard'",
                device_id=device_id,
            )
            return "true" in out.lower()
        except Exception:
            return False
