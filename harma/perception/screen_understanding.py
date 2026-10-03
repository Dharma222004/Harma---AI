"""
Harma Screen Understanding Perception

Combines Phase 2 Computer accessibility tree / UI hierarchy with vision.
Priority:
  1. Accessibility / UI element hierarchy (DOM/OS structured info)
  2. Vision fallback (screenshot analysis & coordinate localization)
"""

from __future__ import annotations

from typing import Any, Optional

from harma.config.logging_config import get_logger
from harma.perception.base import Confidence, ScreenObservation
from harma.perception.vision import VisionProvider, MockVisionProvider

log = get_logger(__name__)


class ScreenPerception:
    """
    Unified screen understanding engine for desktop environments.
    """

    def __init__(self, vision_provider: Optional[VisionProvider] = None) -> None:
        self.vision = vision_provider or MockVisionProvider()

    async def perceive_screen(
        self,
        screenshot_path: Optional[str] = None,
        query: str = "",
        accessibility_tree: Optional[dict[str, Any]] = None,
    ) -> ScreenObservation:
        """
        Perceive screen using accessibility tree first, falling back to vision.
        """
        # Step 1: Check structured accessibility / UI hierarchy
        if accessibility_tree and accessibility_tree.get("elements"):
            log.info("[SCREEN] Using structured accessibility tree (Confidence: VERY_HIGH)")
            elements = accessibility_tree.get("elements", [])
            app_title = accessibility_tree.get("app_title", "Desktop Application")
            ocr_text = "\n".join(e.get("text", "") for e in elements if e.get("text"))

            summary = f"Accessibility hierarchy for '{app_title}' with {len(elements)} elements."
            return ScreenObservation(
                content=summary,
                window_title=app_title,
                bounds=(0, 0, 1920, 1080),
                detected_elements=elements,
                ocr_text=ocr_text,
                active_app=app_title,
                confidence=Confidence.VERY_HIGH,
                source="accessibility_tree",
            )

        # Step 2: Fallback to visual screenshot analysis
        log.info("[SCREEN] Accessibility unavailable or empty. Falling back to vision perception.")
        screenshot = screenshot_path or "desktop_screenshot.png"
        observation = await self.vision.analyze_screenshot(screenshot, query=query)
        return observation

    async def locate_element(
        self,
        query: str,
        screenshot_path: Optional[str] = None,
        accessibility_tree: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Find coordinates of an element matching query.
        Tries accessibility tree first, then vision fallback.
        """
        # Check accessibility tree
        if accessibility_tree:
            for elem in accessibility_tree.get("elements", []):
                name = elem.get("name", "").lower()
                text = elem.get("text", "").lower()
                if query.lower() in name or query.lower() in text:
                    log.info("[SCREEN] Located '%s' via accessibility tree", query)
                    return elem

        # Vision fallback
        screenshot = screenshot_path or "desktop_screenshot.png"
        matches = await self.vision.find_elements(screenshot, query)
        if matches:
            log.info("[SCREEN] Located '%s' via vision provider fallback", query)
            return matches[0]

        log.warning("[SCREEN] Could not locate '%s' via accessibility or vision", query)
        return None
