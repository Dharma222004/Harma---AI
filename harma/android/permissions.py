"""
Harma Android Security & Permission Rules

Enforces strict boundaries around device authentication, lock screens, destructive actions,
and secret protection.
"""

from __future__ import annotations

import re
from typing import Optional

from harma.android.exceptions import SecurityRestrictionError
from harma.config.logging_config import get_logger
from harma.tools.base import PermissionLevel

log = get_logger(__name__)

# Disallowed bypass phrases or targets
_AUTH_BYPASS_PATTERNS = [
    re.compile(r"bypass\s+(?:pin|password|biometric|fingerprint|face\s*unlock|lock|2fa|captcha)", re.IGNORECASE),
    re.compile(r"unlock\s+(?:phone|device|screen)\s+without\s+(?:pin|password|permission)", re.IGNORECASE),
    re.compile(r"crack\s+(?:pin|password|pattern|lock)", re.IGNORECASE),
    re.compile(r"solve\s+captcha", re.IGNORECASE),
]

# Destructive actions requiring HIGH_RISK classification
_HIGH_RISK_ACTIONS = {
    "uninstall",
    "factory_reset",
    "wipe_data",
    "clear_storage",
    "send_payment",
    "financial_transfer",
    "change_pin",
    "change_password",
    "disable_lockscreen",
}


class AndroidSecurity:
    """
    Security validation and policy enforcement for Android actions.
    """

    @staticmethod
    def validate_action_safety(action: str, target: str = "") -> None:
        """
        Verify that an action does not attempt to bypass security or authentication controls.
        Raises SecurityRestrictionError if an prohibited action is detected.
        """
        combined = f"{action} {target}".strip()

        for pattern in _AUTH_BYPASS_PATTERNS:
            if pattern.search(combined):
                log.warning("ANDROID_SECURITY_BLOCKED attempt to bypass authentication: %s", combined)
                raise SecurityRestrictionError(
                    "Action blocked: Harma cannot and will not attempt to bypass device PIN, "
                    "passwords, biometric authentication, device lock, or CAPTCHA. "
                    "Please authenticate on the device directly."
                )

    @staticmethod
    def get_action_permission_level(action: str) -> PermissionLevel:
        """
        Determine the permission level required for an Android action.
        """
        act = action.lower()
        if act in _HIGH_RISK_ACTIONS or any(hr in act for hr in ["uninstall", "reset", "wipe", "transfer", "pay"]):
            return PermissionLevel.HIGH_RISK

        # Sensitive actions that mutate device state or access private data
        sensitive_actions = {
            "tap",
            "tap_element",
            "long_press",
            "swipe",
            "scroll",
            "drag",
            "type_text",
            "press_key",
            "launch_app",
            "close_app",
            "recent_apps",
            "get_clipboard",
            "set_clipboard",
            "get_notifications",
            "open_settings",
        }
        if act in sensitive_actions:
            return PermissionLevel.SENSITIVE

        # Safe read-only actions
        return PermissionLevel.SAFE


class AndroidPermissionManager:
    """
    Centralized Permission Manager for Android Assistant capabilities (Spec §41).
    Tracks, verifies, and requests runtime permissions on-demand.
    Enforces just-in-time permission acquisition per Android 14+ best practices.
    """

    CAPABILITY_PERMISSIONS = {
        "voice": ["android.permission.RECORD_AUDIO"],
        "camera": ["android.permission.CAMERA"],
        "flashlight": ["android.permission.CAMERA"],
        "bluetooth": [
            "android.permission.BLUETOOTH_CONNECT",
            "android.permission.BLUETOOTH_SCAN",
        ],
        "notifications": ["android.permission.POST_NOTIFICATIONS"],
        "location": [
            "android.permission.ACCESS_FINE_LOCATION",
            "android.permission.ACCESS_COARSE_LOCATION",
        ],
        "audio": ["android.permission.MODIFY_AUDIO_SETTINGS"],
        "foreground_mic": [
            "android.permission.FOREGROUND_SERVICE",
            "android.permission.FOREGROUND_SERVICE_MICROPHONE",
        ],
    }

    PERMISSION_EXPLANATIONS = {
        "android.permission.RECORD_AUDIO": "Required for voice interaction and wake-word recognition.",
        "android.permission.CAMERA": "Required to control the flashlight and capture photos.",
        "android.permission.BLUETOOTH_CONNECT": "Required to check or toggle Bluetooth device connectivity.",
        "android.permission.POST_NOTIFICATIONS": "Required to display assistant execution alerts and status.",
        "android.permission.ACCESS_FINE_LOCATION": "Required for map navigation and local services.",
        "android.permission.FOREGROUND_SERVICE_MICROPHONE": "Required by Android 14+ for assistant audio capture in background sessions.",
    }

    def __init__(self, transport: Optional[Any] = None) -> None:
        self._transport = transport
        self._granted_permissions: set[str] = {
            "android.permission.RECORD_AUDIO",
            "android.permission.CAMERA",
            "android.permission.POST_NOTIFICATIONS",
        }

    def check_permission(self, permission: str) -> bool:
        """Check if a specific Android permission is granted."""
        return permission in self._granted_permissions

    def check_capability(self, capability: str) -> tuple[bool, list[str]]:
        """
        Check if all permissions required for a capability are granted.
        Returns (has_all_permissions, missing_permissions_list).
        """
        needed = self.CAPABILITY_PERMISSIONS.get(capability.lower(), [])
        missing = [p for p in needed if not self.check_permission(p)]
        return len(missing) == 0, missing

    def grant_permission(self, permission: str) -> None:
        """Record a granted permission."""
        self._granted_permissions.add(permission)

    def revoke_permission(self, permission: str) -> None:
        """Revoke a permission."""
        self._granted_permissions.discard(permission)

    def explain_permission(self, permission: str) -> str:
        """Return user-friendly justification for requesting this permission."""
        return self.PERMISSION_EXPLANATIONS.get(
            permission, "Required to enable assistant automation features."
        )

    def get_permission_request_flow(self, capability: str) -> dict[str, Any]:
        """
        Produce structured permission request metadata to be handled by Android UI or voice prompt.
        """
        has_perm, missing = self.check_capability(capability)
        if has_perm:
            return {"status": "granted", "capability": capability, "missing": []}

        return {
            "status": "requires_permission",
            "capability": capability,
            "missing": missing,
            "explanations": [self.explain_permission(p) for p in missing],
            "system_intent": "android.settings.APPLICATION_DETAILS_SETTINGS",
        }
