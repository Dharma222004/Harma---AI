"""
Harma Core — Environment Resolver & Device Registry (Spec §25, §26, §27, §44)

Decouples high-level user intent from environment-specific execution.
Resolves whether an action runs on DESKTOP, ANDROID, BROWSER, or MCP,
and enables seamless cross-device execution ("open YouTube on my phone").
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from harma.config.logging_config import get_logger

log = get_logger(__name__)


class EnvironmentType(str, Enum):
    DESKTOP = "desktop"
    ANDROID = "android"
    BROWSER = "browser"
    MCP = "mcp"
    HYBRID = "hybrid"


@dataclass
class DeviceInfo:
    """Registered device profile and operational capabilities."""
    device_id: str
    device_type: EnvironmentType
    name: str
    capabilities: list[str] = field(default_factory=list)
    is_connected: bool = True
    is_active: bool = False
    platform: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def has_capability(self, capability: str) -> bool:
        return capability.lower() in [c.lower() for c in self.capabilities]


class DeviceRegistry:
    """
    Registry of all available execution targets (PC, Android phones, tablets, browsers).
    """

    def __init__(self) -> None:
        self._devices: dict[str, DeviceInfo] = {}
        self._initialize_default_devices()

    def _initialize_default_devices(self) -> None:
        # Default Desktop (this host)
        desktop = DeviceInfo(
            device_id="desktop_local",
            device_type=EnvironmentType.DESKTOP,
            name="Local PC",
            capabilities=[
                "open_application", "close_application", "browser", "browser_automation",
                "screen_capture", "mouse_keyboard", "files", "terminal", "voice",
            ],
            is_connected=True,
            is_active=True,
            metadata={"os": sys.platform},
        )
        self._devices[desktop.device_id] = desktop

    def register_device(self, device: DeviceInfo) -> None:
        self._devices[device.device_id] = device
        log.info("[DEVICES] Registered %s (%s, %d caps)", device.name, device.device_id, len(device.capabilities))

    def register(self, device: DeviceInfo) -> None:
        self.register_device(device)

    def clear(self) -> None:
        self._devices.clear()

    def get_device(self, device_id: str) -> Optional[DeviceInfo]:
        return self._devices.get(device_id)

    def list_devices(self) -> list[DeviceInfo]:
        return list(self._devices.values())

    def get_active_device(self, target_type: Optional[EnvironmentType] = None) -> Optional[DeviceInfo]:
        if target_type:
            for dev in self._devices.values():
                if dev.device_type == target_type and dev.is_connected:
                    return dev
        for dev in self._devices.values():
            if dev.is_active:
                return dev
        return next(iter(self._devices.values()), None) if self._devices else None


class EnvironmentResolver:
    """
    Determines execution target environment based on origin, target device tags,
    and capability matching.
    """

    def __init__(
        self,
        registry: Optional[DeviceRegistry] = None,
        default_environment: EnvironmentType = EnvironmentType.DESKTOP,
    ) -> None:
        self.registry = registry or DeviceRegistry()
        self.default_environment = default_environment

    def resolve(
        self,
        intent_action: str,
        target_device_hint: Optional[str] = None,
        origin_modality: Optional[str] = None,
    ) -> tuple[EnvironmentType, Optional[DeviceInfo]]:
        """
        Resolve which environment and device should handle the requested action.

        Returns (EnvironmentType, DeviceInfo or None).
        """
        # 1. Explicit user target device tag ("on my phone" / "on my laptop")
        if target_device_hint:
            hint = target_device_hint.lower().strip()
            if hint in ("android", "phone", "mobile", "handset"):
                dev = self.registry.get_active_device(EnvironmentType.ANDROID)
                return EnvironmentType.ANDROID, dev
            elif hint in ("desktop", "laptop", "pc", "computer", "windows"):
                dev = self.registry.get_active_device(EnvironmentType.DESKTOP)
                return EnvironmentType.DESKTOP, dev

        # 2. Origin modality constraint (e.g. request made from Android runtime)
        if origin_modality == "android_voice" or origin_modality == "android_app":
            dev = self.registry.get_active_device(EnvironmentType.ANDROID)
            return EnvironmentType.ANDROID, dev

        # 3. Dedicated capability routing (actions that exclusively belong to Android)
        android_exclusive = {
            "flashlight", "toggle_flashlight", "android.flashlight",
            "android.wifi", "android.mobile_data", "android.bluetooth",
            "android.volume", "android.navigate", "android.camera",
        }
        low = intent_action.lower()
        if low in android_exclusive or low.startswith("android.") or any(k in low for k in ("flashlight", "torch")):
            dev = self.registry.get_active_device(EnvironmentType.ANDROID)
            return EnvironmentType.ANDROID, dev

        # 4. Default to host environment
        dev = self.registry.get_active_device(self.default_environment)
        return self.default_environment, dev

    def resolve_for_request(self, request: Any) -> EnvironmentType:
        """Convenience method resolving EnvironmentType from a HarmaRequest or prompt string."""
        clean = getattr(request, "clean_goal", str(request))
        target_hint = getattr(request, "target_device", None)
        modality = getattr(request, "modality", None)
        mod_str = modality.value if hasattr(modality, "value") else str(modality or "")

        env, _ = self.resolve(
            intent_action=clean,
            target_device_hint=target_hint,
            origin_modality=mod_str,
        )
        return env


# Singleton instance accessor
_global_device_registry: Optional[DeviceRegistry] = None
_global_environment_resolver: Optional[EnvironmentResolver] = None


def get_device_registry() -> DeviceRegistry:
    global _global_device_registry
    if _global_device_registry is None:
        _global_device_registry = DeviceRegistry()
    return _global_device_registry


def get_environment_resolver() -> EnvironmentResolver:
    global _global_environment_resolver
    if _global_environment_resolver is None:
        _global_environment_resolver = EnvironmentResolver(get_device_registry())
    return _global_environment_resolver
