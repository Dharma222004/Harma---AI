"""
Harma Browser Vision Perception

Integrates Phase 3 Browser automation with multimodal perception.
Priority:
  1. DOM / Accessibility tree (DOM-first automation)
  2. Structured UI snapshot
  3. Vision fallback (screenshot reasoning)
  4. Computer-use fallback
"""

from __future__ import annotations

from typing import Any, Optional

from harma.config.logging_config import get_logger
from harma.perception.base import Confidence, ScreenObservation
from harma.perception.vision import VisionProvider, MockVisionProvider

log = get_logger(__name__)


class BrowserVision:
    """
    Multimodal perception for web browser pages.
    """

    def __init__(self, vision_provider: Optional[VisionProvider] = None) -> None:
        self.vision = vision_provider or MockVisionProvider()

    async def inspect_page(
        self,
        dom_snapshot: Optional[dict[str, Any]] = None,
        screenshot_path: Optional[str] = None,
        query: str = "",
    ) -> ScreenObservation:
        """
        Inspect webpage state following DOM-first priority with visual fallback.
        """
        # Priority 1 & 2: DOM and Structured UI
        if dom_snapshot and (dom_snapshot.get("elements") or dom_snapshot.get("text")):
            elements = dom_snapshot.get("elements", [])
            text_content = dom_snapshot.get("text", "")
            title = dom_snapshot.get("title", "Browser Webpage")
            url = dom_snapshot.get("url", "")

            content = (
                f"Webpage '{title}' ({url}). "
                f"DOM elements count: {len(elements)}. "
                f"Visible text: {text_content[:300]}"
            )
            log.info("[BROWSER_VISION] Inspected via DOM-first architecture (Confidence: HIGH)")
            return ScreenObservation(
                content=content,
                window_title=title,
                detected_elements=elements,
                ocr_text=text_content,
                active_app="Browser",
                confidence=Confidence.HIGH,
                source="browser_dom",
                metadata={"url": url},
            )

        # Priority 3: Vision fallback when DOM is empty, canvas-based, or blocked
        log.info("[BROWSER_VISION] DOM insufficient. Falling back to visual screenshot analysis.")
        screenshot = screenshot_path or "browser_page.png"
        observation = await self.vision.analyze_screenshot(screenshot, query=query)
        observation.source = "browser_vision_fallback"
        return observation

    async def find_web_element(
        self,
        query: str,
        dom_elements: Optional[list[dict[str, Any]]] = None,
        screenshot_path: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Find web element by query. Tries DOM first, then visual fallback.
        """
        if dom_elements:
            for elem in dom_elements:
                text = elem.get("text", "").lower()
                selector = elem.get("selector", "").lower()
                aria = elem.get("aria_label", "").lower()
                if any(term in text or term in selector or term in aria for term in query.lower().split()):
                    log.info("[BROWSER_VISION] Located web element '%s' via DOM", query)
                    return elem

        # Visual fallback
        screenshot = screenshot_path or "browser_page.png"
        matches = await self.vision.find_elements(screenshot, query)
        if matches:
            log.info("[BROWSER_VISION] Located web element '%s' via Vision fallback", query)
            return matches[0]

        return None
