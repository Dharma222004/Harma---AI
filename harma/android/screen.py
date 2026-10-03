"""
Harma Android Screen Observation

Handles capturing screenshots, retrieving UI hierarchy, detecting sensitive data,
and producing structured ScreenObservation objects for the agent.
"""

from __future__ import annotations

import re
import time
from typing import Optional

from harma.android.accessibility import UIHierarchyParser
from harma.android.models import ScreenObservation, UIElement
from harma.android.transports.base import AndroidTransport
from harma.config.logging_config import get_logger

log = get_logger(__name__)

# Patterns for detecting obvious sensitive information on screen
_PASSWORD_PATTERN = re.compile(r"password|pin|passcode|secret|credential", re.IGNORECASE)
_OTP_PATTERN = re.compile(r"\b\d{4,8}\b")
_CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,16}\b")


class ScreenObserver:
    """
    Coordinates Android screen observations.
    """

    def __init__(
        self,
        transport: AndroidTransport,
        include_screenshots: bool = True,
        detect_secrets: bool = True,
    ) -> None:
        self.transport = transport
        self.include_screenshots = include_screenshots
        self.detect_secrets = detect_secrets
        self.parser = UIHierarchyParser()

    async def observe(self, device_id: str) -> ScreenObservation:
        """
        Capture complete screen observation: UI hierarchy + optional screenshot.
        """
        start_time = time.time()

        # 1. Check lock state
        is_locked = await self.transport.is_locked(device_id)

        # 2. Get current app & activity
        pkg, act = await self.transport.get_current_app(device_id)

        # 3. Get UI hierarchy XML
        elements: list[UIElement] = []
        try:
            xml_dump = await self.transport.get_ui_hierarchy(device_id)
            elements = self.parser.parse(xml_dump)
        except Exception as exc:
            log.warning("Failed to extract UI hierarchy: %s", exc)

        # 4. Detect & redact secrets if enabled
        if self.detect_secrets:
            self._redact_secrets(elements)

        # 5. Capture screenshot if configured
        shot_bytes: Optional[bytes] = None
        if self.include_screenshots:
            try:
                shot_bytes = await self.transport.capture_screenshot(device_id)
            except Exception as exc:
                log.warning("Failed to capture screenshot: %s", exc)

        # 6. Extract screen dimensions from root element or default
        w, h = 1080, 2400
        if elements and elements[0].bounds.width > 0:
            w = elements[0].bounds.width
            h = elements[0].bounds.height

        summary = self.parser.build_summary(elements)
        if is_locked:
            summary = "[DEVICE LOCKED] " + summary

        elapsed = time.time() - start_time
        log.debug("Screen observation completed in %.2fs (%d elements)", elapsed, len(elements))

        return ScreenObservation(
            device_id=device_id,
            timestamp=time.time(),
            width=w,
            height=h,
            current_package=pkg,
            current_activity=act,
            elements=elements,
            screenshot_bytes=shot_bytes,
            is_locked=is_locked,
            summary=summary,
        )

    def _redact_secrets(self, elements: list[UIElement]) -> None:
        """Mask sensitive content on screen so secrets are never propagated or persisted."""
        for el in elements:
            if el.password:
                el.text = "••••••••"
                el.content_description = "[PASSWORD REDACTED]"
            elif el.text and _PASSWORD_PATTERN.search(el.id or el.content_description or ""):
                el.text = "••••••••"
            elif el.text and _CARD_PATTERN.search(el.text):
                el.text = "[PAYMENT CARD REDACTED]"
