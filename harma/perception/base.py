"""
Harma Perception Base Models

Provides unified observation primitives for multimodal perception:
- Text
- Image
- Screenshot
- Document
- Structured Data

Includes confidence metadata and untrusted content boundaries.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ObservationType(str, Enum):
    """Types of multimodal observations."""
    TEXT = "text"
    IMAGE = "image"
    SCREENSHOT = "screenshot"
    DOCUMENT = "document"
    PDF = "pdf"
    STRUCTURED_DATA = "structured_data"


class Confidence(str, Enum):
    """
    Confidence levels reflecting evidence quality (NOT model self-confidence).

    VERY_HIGH — Verified via authoritative API, OS accessibility tree, or exit code.
    HIGH      — Direct UI confirmation or strongly parsed DOM text.
    MEDIUM    — Vision-only interpretation, OCR reading, or parsed document.
    LOW       — Model inference, speculative assumption, or partial match.
    UNKNOWN   — Unverified or inconclusive evidence.
    """
    VERY_HIGH = "very_high"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"

    @property
    def score(self) -> float:
        """Numeric score for ranking and comparison."""
        mapping = {
            Confidence.VERY_HIGH: 1.0,
            Confidence.HIGH: 0.8,
            Confidence.MEDIUM: 0.5,
            Confidence.LOW: 0.2,
            Confidence.UNKNOWN: 0.0,
        }
        return mapping.get(self, 0.0)


@dataclass
class Observation:
    """
    Base observation representing any perceived datum from the environment.
    """
    content: str = ""
    type: ObservationType = ObservationType.TEXT
    source: str = "environment"
    confidence: Confidence = Confidence.MEDIUM
    sensitivity: str = "public"  # public | internal | confidential | restricted
    is_untrusted: bool = True     # External data is untrusted by default
    raw_data: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: float = field(default_factory=time.time)

    def to_envelope(self) -> str:
        """
        Wrap content in an untrusted data envelope to prevent prompt injection.
        """
        if self.is_untrusted:
            return (
                f'<untrusted_data source="{self.source}" type="{self.type.value}" '
                f'confidence="{self.confidence.value}">\n{self.content}\n</untrusted_data>'
            )
        return self.content


@dataclass
class TextObservation(Observation):
    """Text-based observation."""
    type: ObservationType = ObservationType.TEXT


@dataclass
class ImageObservation(Observation):
    """Image perception observation."""
    type: ObservationType = ObservationType.IMAGE
    image_path: str = ""
    dimensions: tuple[int, int] = (0, 0)
    format: str = "png"
    detected_objects: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class ScreenObservation(Observation):
    """Computer or mobile device screen perception."""
    type: ObservationType = ObservationType.SCREENSHOT
    window_title: str = ""
    bounds: tuple[int, int, int, int] = (0, 0, 0, 0)
    detected_elements: list[dict[str, Any]] = field(default_factory=list)
    ocr_text: str = ""
    active_app: str = ""


@dataclass
class DocumentObservation(Observation):
    """Document perception observation (TXT, MD, PDF, DOCX, CSV)."""
    type: ObservationType = ObservationType.DOCUMENT
    file_path: str = ""
    file_type: str = "txt"
    page_count: int = 1
    sections: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    entities: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class StructuredObservation(Observation):
    """Schema-validated structured data observation."""
    type: ObservationType = ObservationType.STRUCTURED_DATA
    schema_name: str = ""
    data: dict[str, Any] = field(default_factory=dict)
