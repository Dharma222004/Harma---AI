"""
Harma Android Subsystem (Phase 6)

Provides comprehensive Android mobile device control:
- Device lifecycle & discovery
- Screen observation & UI hierarchy parsing
- Element-based & coordinate-based touch actions
- Keyboard actions & system navigation
- App lifecycle & discovery
- Clipboard & notifications with privacy safeguards
- Observe → Act → Verify cycle integration
"""

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
from harma.android.manager import (
    AndroidManager,
    get_android_manager,
    set_android_manager,
)
from harma.android.transports.base import AndroidTransport
from harma.android.transports.adb import ADBTransport
from harma.android.transports.mock import FakeAndroidTransport
from harma.android.tools import get_android_tools

__all__ = [
    # Exceptions
    "AndroidError",
    "DeviceNotFoundError",
    "DeviceConnectionError",
    "DeviceLockedError",
    "MultipleDevicesError",
    "ElementNotFoundError",
    "AppNotFoundError",
    "AmbiguousAppError",
    "ActionTimeoutError",
    "SecurityRestrictionError",
    "TransportError",
    # Models
    "AndroidDevice",
    "DeviceConnectionState",
    "DeviceStatus",
    "ScreenObservation",
    "UIElement",
    "Bounds",
    "Point",
    "AppInfo",
    "NotificationItem",
    "AndroidActionResult",
    # Transports
    "AndroidTransport",
    "ADBTransport",
    "FakeAndroidTransport",
    # Manager
    "AndroidManager",
    "get_android_manager",
    "set_android_manager",
    # Tools
    "get_android_tools",
]
