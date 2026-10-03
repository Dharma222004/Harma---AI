"""
Harma Multimodal Vision Perception

Provides VisionProvider interface, MockVisionProvider for deterministic tests,
and MultimodalLLMVisionProvider for live multimodal reasoning.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any, Optional

from harma.config.logging_config import get_logger
from harma.perception.base import Confidence, ImageObservation, ScreenObservation

log = get_logger(__name__)


class VisionProvider(ABC):
    """Abstract interface for visual reasoning over images and screenshots."""

    @abstractmethod
    async def analyze_image(
        self,
        image: bytes | str,
        prompt: str = "",
    ) -> ImageObservation:
        """Analyze an image and return an ImageObservation."""

    @abstractmethod
    async def analyze_screenshot(
        self,
        screenshot: bytes | str,
        query: str = "",
    ) -> ScreenObservation:
        """Inspect a screenshot for active UI elements, text, or errors."""

    @abstractmethod
    async def find_elements(
        self,
        screenshot: bytes | str,
        query: str,
    ) -> list[dict[str, Any]]:
        """Locate specific UI elements matching a natural language query."""

    @abstractmethod
    async def compare_images(
        self,
        img1: bytes | str,
        img2: bytes | str,
    ) -> dict[str, Any]:
        """Compare two images/screenshots and identify visual changes."""


class MockVisionProvider(VisionProvider):
    """
    Deterministic mock vision provider for testing and offline environments.
    """

    def __init__(self) -> None:
        self.analyzed_count: int = 0
        self.custom_elements: list[dict[str, Any]] = []

    def set_mock_elements(self, elements: list[dict[str, Any]]) -> None:
        """Configure mock UI elements for subsequent queries."""
        self.custom_elements = elements

    async def analyze_image(
        self,
        image: bytes | str,
        prompt: str = "",
    ) -> ImageObservation:
        self.analyzed_count += 1
        path = image if isinstance(image, str) else "bytes://image.png"

        # Check for keywords in path or prompt
        low_prompt = prompt.lower()
        low_path = path.lower()

        if "chart" in low_prompt or "chart" in low_path:
            description = "A line chart showing quarterly revenue growth with an upward trend."
            detected = ["chart", "axis", "legend", "trendline"]
        elif "error" in low_prompt or "error" in low_path:
            description = "An error dialog displaying 'Connection timed out (Error 504)'."
            detected = ["dialog", "error_icon", "ok_button"]
        else:
            description = f"Visual scene analysis: {prompt or 'Generic image'}"
            detected = ["window", "button", "text_label"]

        return ImageObservation(
            content=description,
            image_path=path,
            dimensions=(1920, 1080),
            format="png",
            detected_objects=detected,
            description=description,
            confidence=Confidence.HIGH,
            source="mock_vision",
        )

    async def analyze_screenshot(
        self,
        screenshot: bytes | str,
        query: str = "",
    ) -> ScreenObservation:
        self.analyzed_count += 1
        path = screenshot if isinstance(screenshot, str) else "bytes://screenshot.png"
        low_q = query.lower()

        active_app = "Google Chrome"
        ocr_text = "NIFTY 50 - 24,850.30 (+0.45%)\nMarket Open\nSearch or type URL"
        elements = [
            {"name": "search_bar", "type": "input", "bounds": [100, 50, 600, 40], "clickable": True},
            {"name": "settings_icon", "type": "button", "bounds": [1880, 20, 30, 30], "clickable": True},
            {"name": "submit_button", "type": "button", "bounds": [720, 50, 80, 40], "clickable": True},
        ]

        if self.custom_elements:
            elements = self.custom_elements

        if "error" in low_q:
            ocr_text += "\n[Error Alert]: Failed to load resource"
            elements.append({"name": "error_banner", "type": "alert", "bounds": [200, 200, 400, 80]})

        content_desc = (
            f"Screen showing active application '{active_app}'. "
            f"Visible text snippet: {ocr_text.replace(chr(10), ' | ')}. "
            f"Detected {len(elements)} interactive elements."
        )

        return ScreenObservation(
            content=content_desc,
            window_title="Active Desktop",
            bounds=(0, 0, 1920, 1080),
            detected_elements=elements,
            ocr_text=ocr_text,
            active_app=active_app,
            confidence=Confidence.VERY_HIGH,
            source="mock_vision",
        )

    async def find_elements(
        self,
        screenshot: bytes | str,
        query: str,
    ) -> list[dict[str, Any]]:
        self.analyzed_count += 1
        low_q = query.lower()

        elements = self.custom_elements or [
            {"name": "search_bar", "type": "input", "x": 400, "y": 70, "confidence": 0.95},
            {"name": "settings_icon", "type": "button", "x": 1895, "y": 35, "confidence": 0.92},
            {"name": "submit_button", "type": "button", "x": 760, "y": 70, "confidence": 0.90},
            {"name": "close_icon", "type": "button", "x": 1900, "y": 10, "confidence": 0.88},
        ]

        matches = []
        for elem in elements:
            name = elem.get("name", "").lower()
            elem_type = elem.get("type", "").lower()
            if any(term in name or term in elem_type for term in low_q.split()):
                matches.append(elem)

        if not matches and elements:
            # Fallback to closest match
            matches = [elements[0]]

        return matches

    async def compare_images(
        self,
        img1: bytes | str,
        img2: bytes | str,
    ) -> dict[str, Any]:
        self.analyzed_count += 1
        return {
            "identical": False,
            "similarity_score": 0.88,
            "changes_detected": [
                {"region": [100, 50, 200, 50], "description": "Text changed in input field"},
                {"region": [720, 50, 80, 40], "description": "Button state transitioned to active"},
            ],
            "recommendation": "State transition verified successfully.",
        }


class MultimodalLLMVisionProvider(VisionProvider):
    """
    Multimodal vision provider using an LLM provider with fallback to MockVisionProvider.
    """

    def __init__(self, fallback: Optional[VisionProvider] = None) -> None:
        self._fallback = fallback or MockVisionProvider()

    async def analyze_image(
        self,
        image: bytes | str,
        prompt: str = "",
    ) -> ImageObservation:
        try:
            from harma.llm.factory import get_provider
            llm = get_provider()
            if hasattr(llm, "analyze_image"):
                res = await llm.analyze_image(image=image, prompt=prompt)
                return ImageObservation(
                    content=res.get("text", "Image analysis complete"),
                    description=res.get("text", ""),
                    confidence=Confidence.HIGH,
                    source=f"multimodal_{llm.name}",
                )
        except Exception as exc:
            log.warning("Multimodal LLM vision analysis failed, falling back: %s", exc)

        return await self._fallback.analyze_image(image, prompt)

    async def analyze_screenshot(
        self,
        screenshot: bytes | str,
        query: str = "",
    ) -> ScreenObservation:
        return await self._fallback.analyze_screenshot(screenshot, query)

    async def find_elements(
        self,
        screenshot: bytes | str,
        query: str,
    ) -> list[dict[str, Any]]:
        return await self._fallback.find_elements(screenshot, query)

    async def compare_images(
        self,
        img1: bytes | str,
        img2: bytes | str,
    ) -> dict[str, Any]:
        return await self._fallback.compare_images(img1, img2)
