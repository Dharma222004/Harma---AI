"""
Harma Unified Context Models

Defines the structured context primitives for Unified Context Fusion.
Every item carries source, timestamp, confidence, sensitivity, and trust level.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from harma.intelligence.plan_models import Plan
from harma.perception.base import Confidence


class TrustLevel(str, Enum):
    """Authority and trust classification."""
    SYSTEM = "system"        # Hardcoded system instructions / safety policy
    USER = "user"            # Current verified user instructions
    TRUSTED = "trusted"      # Internal agent execution state & plans
    UNTRUSTED = "untrusted"  # Memory, external services, emails, web pages, tool data


@dataclass
class ContextItem:
    """An individual piece of context with provenance metadata."""
    source: str
    content: str
    trust_level: TrustLevel = TrustLevel.UNTRUSTED
    confidence: Confidence = Confidence.MEDIUM
    sensitivity: str = "public"
    relevance: float = 1.0
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_safe_prompt_text(self) -> str:
        """
        Render as clean text if trusted, or inside an untrusted data envelope if untrusted.
        """
        if self.trust_level in (TrustLevel.SYSTEM, TrustLevel.USER, TrustLevel.TRUSTED):
            return self.content
        return f'<untrusted_data source="{self.source}" sensitivity="{self.sensitivity}">\n{self.content}\n</untrusted_data>'


@dataclass
class UnifiedContext:
    """
    Fused context combining all agent perceptual and memory channels.
    """
    user_request: str = ""
    explicit_corrections: list[ContextItem] = field(default_factory=list)
    observations: list[ContextItem] = field(default_factory=list)
    active_tasks: list[ContextItem] = field(default_factory=list)
    conversation: list[ContextItem] = field(default_factory=list)
    short_term_memory: list[ContextItem] = field(default_factory=list)
    long_term_memory: list[ContextItem] = field(default_factory=list)
    external_service_data: list[ContextItem] = field(default_factory=list)
    browser_state: Optional[ContextItem] = None
    computer_state: Optional[ContextItem] = None
    android_state: Optional[ContextItem] = None
    current_plan: Optional[Plan] = None
    permissions: list[str] = field(default_factory=list)
    user_preferences: dict[str, Any] = field(default_factory=dict)
    system_rules: str = ""
