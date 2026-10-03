"""
Harma Android Notifications Controller

Provides controlled observation of Android notifications.
Ensures notification data is never auto-persisted into long-term memory.
"""

from __future__ import annotations

import re
from typing import Optional

from harma.android.models import NotificationItem
from harma.android.transports.base import AndroidTransport
from harma.config.logging_config import get_logger

log = get_logger(__name__)

# Patterns for detecting OTPs or sensitive notification content
_OTP_PATTERN = re.compile(r"\b(\d{4,8})\b")


class NotificationManager:
    """
    Manages Android notifications observation.
    """

    def __init__(self, transport: AndroidTransport) -> None:
        self.transport = transport

    async def get_notifications(
        self, device_id: str, mask_sensitive: bool = True
    ) -> list[NotificationItem]:
        """
        Retrieve active notifications.
        If mask_sensitive is True, masks potential OTPs or credentials.
        """
        notifications = await self.transport.get_notifications(device_id)
        log.info(
            "ANDROID_NOTIFICATIONS_RETRIEVED device_id=%s count=%d",
            device_id,
            len(notifications),
        )

        if not mask_sensitive:
            return notifications

        masked: list[NotificationItem] = []
        for n in notifications:
            safe_text = n.text
            if "otp" in n.title.lower() or "code" in n.title.lower() or "verification" in n.title.lower():
                safe_text = _OTP_PATTERN.sub("••••••", safe_text)
            masked.append(
                NotificationItem(
                    id=n.id,
                    package=n.package,
                    app_name=n.app_name or n.package.split(".")[-1].capitalize(),
                    title=n.title,
                    text=safe_text,
                    timestamp=n.timestamp,
                    is_ongoing=n.is_ongoing,
                )
            )

        return masked
