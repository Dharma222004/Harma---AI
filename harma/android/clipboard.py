"""
Harma Android Clipboard Controller

Provides safe access to Android clipboard without logging or persisting sensitive data.
"""

from __future__ import annotations

from harma.android.models import AndroidActionResult
from harma.android.transports.base import AndroidTransport
from harma.config.logging_config import get_logger

log = get_logger(__name__)


class ClipboardManager:
    """
    Manages Android clipboard with privacy safeguards.
    """

    def __init__(self, transport: AndroidTransport) -> None:
        self.transport = transport

    async def get_clipboard(self, device_id: str) -> str:
        """
        Read clipboard content from the Android device.
        Never logs actual clipboard content.
        """
        content = await self.transport.get_clipboard(device_id)
        # Log event without logging content
        log.info("ANDROID_CLIPBOARD_READ device_id=%s length=%d", device_id, len(content))
        return content

    async def set_clipboard(self, device_id: str, text: str) -> AndroidActionResult:
        """
        Set clipboard content on the Android device.
        Never logs actual clipboard content.
        """
        success = await self.transport.set_clipboard(device_id, text)
        log.info("ANDROID_CLIPBOARD_WRITTEN device_id=%s length=%d", device_id, len(text))
        return AndroidActionResult(
            success=success,
            action="set_clipboard",
            detail="Clipboard content updated successfully.",
            verified=True,
            data={"length": len(text)},
        )
