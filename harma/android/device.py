"""
Harma Android Device Controller

Handles device discovery, connection lifecycle, multi-device ambiguity,
and device status retrieval.
"""

from __future__ import annotations

from typing import Optional

from harma.android.exceptions import (
    DeviceLockedError,
    DeviceNotFoundError,
    MultipleDevicesError,
)
from harma.android.models import AndroidDevice, DeviceStatus
from harma.android.transports.base import AndroidTransport
from harma.config.logging_config import get_logger

log = get_logger(__name__)


class DeviceController:
    """
    Manages Android device connections, discovery, and status inspection.
    """

    def __init__(self, transport: AndroidTransport) -> None:
        self.transport = transport
        self.active_device: Optional[AndroidDevice] = None

    async def list_devices(self) -> list[AndroidDevice]:
        """Discover all connected Android devices."""
        devices = await self.transport.list_devices()
        log.info("ANDROID_DEVICES_DISCOVERED count=%d", len(devices))
        return devices

    async def resolve_target_device(self, requested_id: Optional[str] = None) -> str:
        """
        Resolve which device to use.
        - If requested_id is provided, returns it.
        - If active_device is already connected and valid, returns its ID.
        - If only 1 device exists, auto-selects it.
        - If 0 devices exist, raises DeviceNotFoundError.
        - If multiple exist and none selected, raises MultipleDevicesError.
        """
        if requested_id:
            return requested_id

        if self.active_device:
            return self.active_device.device_id

        devices = await self.list_devices()
        connected = [d for d in devices if d.state.value == "connected"]

        if not connected:
            raise DeviceNotFoundError("No connected Android devices found.")

        if len(connected) == 1:
            return connected[0].device_id

        # Multiple devices detected
        raise MultipleDevicesError([d.device_id for d in connected])

    async def connect(self, device_id: Optional[str] = None) -> AndroidDevice:
        """Connect to an Android device."""
        target_id = await self.resolve_target_device(device_id)
        device = await self.transport.connect(target_id)
        self.active_device = device
        log.info(
            "ANDROID_DEVICE_CONNECTED device_id=%s model=%s manufacturer=%s",
            device.device_id,
            device.model,
            device.manufacturer,
        )
        return device

    async def disconnect(self, device_id: Optional[str] = None) -> bool:
        """Disconnect the active or specified device."""
        target_id = device_id or (self.active_device.device_id if self.active_device else None)
        if not target_id:
            return True

        success = await self.transport.disconnect(target_id)
        if self.active_device and self.active_device.device_id == target_id:
            self.active_device = None
        log.info("ANDROID_DEVICE_DISCONNECTED device_id=%s", target_id)
        return success

    async def get_status(self, device_id: Optional[str] = None) -> DeviceStatus:
        """Fetch current operational status of the target device."""
        target_id = await self.resolve_target_device(device_id)
        status = await self.transport.get_device_status(target_id)
        return status

    async def check_lock_state(self, device_id: Optional[str] = None) -> bool:
        """Check if target device is locked."""
        target_id = await self.resolve_target_device(device_id)
        return await self.transport.is_locked(target_id)
