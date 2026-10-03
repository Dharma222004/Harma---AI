"""
Harma Android Exceptions

Defines the error hierarchy for the Android control subsystem.
"""

from __future__ import annotations


class AndroidError(Exception):
    """Base exception for all Android subsystem errors."""

    def __init__(self, message: str, code: str = "ANDROID_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class DeviceNotFoundError(AndroidError):
    """Raised when a specified or default device cannot be found."""

    def __init__(self, message: str = "No connected Android device found.") -> None:
        super().__init__(message, code="DEVICE_NOT_FOUND")


class DeviceConnectionError(AndroidError):
    """Raised when communication with the Android device fails."""

    def __init__(self, message: str = "Failed to connect to Android device.") -> None:
        super().__init__(message, code="DEVICE_CONNECTION_ERROR")


class DeviceLockedError(AndroidError):
    """Raised when the Android device is locked and requires user unlocking."""

    def __init__(
        self,
        message: str = "Android device is locked. Please unlock the device manually to proceed.",
    ) -> None:
        super().__init__(message, code="DEVICE_LOCKED")


class MultipleDevicesError(AndroidError):
    """Raised when multiple devices are detected and no device ID was specified."""

    def __init__(self, device_ids: list[str]) -> None:
        ids_str = ", ".join(device_ids)
        super().__init__(
            f"Multiple Android devices found: [{ids_str}]. Please specify which device to use.",
            code="MULTIPLE_DEVICES",
        )
        self.device_ids = device_ids


class ElementNotFoundError(AndroidError):
    """Raised when a UI element cannot be located on the current screen."""

    def __init__(self, query: str) -> None:
        super().__init__(
            f"UI element matching '{query}' was not found on screen.",
            code="ELEMENT_NOT_FOUND",
        )
        self.query = query


class AppNotFoundError(AndroidError):
    """Raised when an application is not installed on the device."""

    def __init__(self, app_name: str, suggestions: list[str] | None = None) -> None:
        msg = f"Application '{app_name}' is not installed on the device."
        if suggestions:
            msg += f" Did you mean: {', '.join(suggestions)}?"
        super().__init__(msg, code="APP_NOT_FOUND")
        self.app_name = app_name
        self.suggestions = suggestions or []


class AmbiguousAppError(AndroidError):
    """Raised when an app query matches multiple installed apps."""

    def __init__(self, app_name: str, candidates: list[str]) -> None:
        super().__init__(
            f"Application name '{app_name}' is ambiguous. Found: {', '.join(candidates)}. Please clarify.",
            code="AMBIGUOUS_APP",
        )
        self.app_name = app_name
        self.candidates = candidates


class ActionTimeoutError(AndroidError):
    """Raised when an Android action or observation times out."""

    def __init__(self, action: str, timeout: float) -> None:
        super().__init__(
            f"Android action '{action}' timed out after {timeout} seconds.",
            code="ACTION_TIMEOUT",
        )
        self.action = action
        self.timeout = timeout


class SecurityRestrictionError(AndroidError):
    """Raised when an action violates security policy (e.g. bypassing auth/PIN)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="SECURITY_RESTRICTION")


class TransportError(AndroidError):
    """Raised when the underlying Android transport (ADB / mock) encounters an error."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="TRANSPORT_ERROR")
