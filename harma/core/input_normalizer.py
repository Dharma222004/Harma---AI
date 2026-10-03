"""
Harma Core — Unified Input Architecture & Normalizer (Spec §2, §31, §32, §33)

All interaction modalities (Voice, Text, API, Control Center, Scheduled Tasks)
flow through the Input Normalizer to produce a single authoritative HarmaRequest.

    TEXT / VOICE / API / SCHEDULED
                  ↓
          INPUT NORMALIZER
                  ↓
            HARMA REQUEST
                  ↓
             HARMA RUNNER
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from harma.config.logging_config import get_logger
from harma.voice.language import (
    classify_yes_no,
    detect_language_switch,
    is_cancel_command,
    is_end_conversation,
    is_reset_command,
    is_shutdown_command,
    normalize,
    resolve_language,
    strip_wake_phrase,
    Language,
    ENGLISH,
)

log = get_logger(__name__)


class InputModality(str, Enum):
    VOICE = "voice"
    TEXT = "text"
    API = "api"
    SCHEDULED = "scheduled"
    CONTROL_CENTER = "control_center"


class ActionRisk(str, Enum):
    SAFE = "safe"
    CONSEQUENTIAL = "consequential"  # payments, delete, send message, publish, shutdown
    HIGH_RISK = "high_risk"


@dataclass
class HarmaRequest:
    """
    Canonical, normalized request representation processed by HarmaRunner.
    """
    request_id: str
    clean_goal: str                      # Normalized text with wake-phrase stripped
    raw_input: str                       # Exact original input string
    modality: InputModality
    language: Language                   # Detected or active spoken/written language
    confidence: float = 1.0              # ASR confidence (1.0 for typed text/API)
    created_at: float = field(default_factory=time.time)
    target_device: Optional[str] = None  # "android", "phone", "desktop", "laptop", or None
    is_control_command: bool = False     # shutdown, cancel, reset, language switch
    control_intent: Optional[str] = None # "cancel", "shutdown", "reset", "lang_switch"
    risk_level: ActionRisk = ActionRisk.SAFE
    requires_confirmation: bool = False
    confirmation_reason: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


# Regex patterns identifying consequential or sensitive actions requiring confirmation
_CONSEQUENTIAL_PATTERNS = [
    re.compile(r"\b(send|transfer|pay|purchase|buy)\b.{1,40}\b(money|rupees|inr|\$|rs|bucks|cash|₹|\d+)\b", re.IGNORECASE),
    re.compile(r"\b(delete|erase|format|wipe|destroy|remove)\b.{1,30}\b(file|files|data|database|folder|account|message|all)\b", re.IGNORECASE),
    re.compile(r"\b(send|text|dm|mail|email)\b.{1,50}\b(to|saying|message|msg)\b", re.IGNORECASE),
    re.compile(r"\b(shutdown|shut down|reboot|restart|power off)\b", re.IGNORECASE),
    re.compile(r"\b(book|reserve)\b.{1,30}\b(tickets?|flight|hotel|room)\b", re.IGNORECASE),
]

# Patterns detecting target device references in user instructions
_DEVICE_PATTERNS = [
    (re.compile(r"\b(on|to|from)\s+(my\s+)?(phone|mobile|android|handset|device)\b", re.IGNORECASE), "android"),
    (re.compile(r"\b(on|to|from)\s+(my\s+)?(pc|laptop|computer|desktop|windows)\b", re.IGNORECASE), "desktop"),
]


class InputNormalizer:
    """
    Normalizes requests across Text, Voice, API, and Control Center.
    Enforces unified representation, wake phrase stripping, device resolution,
    multilingual intent awareness, and safety classification.
    """

    def __init__(self, default_language: Optional[Language] = None) -> None:
        self.default_language = default_language or ENGLISH

    def normalize(
        self,
        raw_text: str,
        modality: InputModality = InputModality.TEXT,
        confidence: float = 1.0,
        language: Optional[Language | str] = None,
        request_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> HarmaRequest:
        req_id = request_id or f"req_{uuid.uuid4().hex[:10]}"
        raw = (raw_text or "").strip()
        lang = resolve_language(language, default=self.default_language)

        # 1. Clean wake word
        cleaned = strip_wake_phrase(raw)
        if not cleaned:
            cleaned = raw

        # 2. Extract explicit target device (e.g. "open YouTube on my phone")
        target_device = None
        for pattern, dev in _DEVICE_PATTERNS:
            if pattern.search(cleaned):
                target_device = dev
                break

        # 3. Detect system control intents
        is_control = False
        control_intent = None

        meta = dict(metadata or {})
        switched_lang = detect_language_switch(cleaned) or detect_language_switch(raw)
        if is_shutdown_command(cleaned) or is_shutdown_command(raw):
            is_control = True
            control_intent = "shutdown"
        elif is_cancel_command(cleaned) or is_cancel_command(raw):
            is_control = True
            control_intent = "cancel"
        elif is_reset_command(cleaned) or is_reset_command(raw):
            is_control = True
            control_intent = "reset"
        elif switched_lang:
            is_control = True
            control_intent = "lang_switch"
            meta["target_language"] = switched_lang

        # 4. Assess risk & consequential action safety (Spec §31, §32)
        risk = ActionRisk.SAFE
        req_confirm = False
        confirm_reason = None

        # Check for consequential patterns
        for pattern in _CONSEQUENTIAL_PATTERNS:
            if pattern.search(cleaned):
                risk = ActionRisk.CONSEQUENTIAL
                break

        # Consequential action safety policy
        if risk == ActionRisk.CONSEQUENTIAL:
            req_confirm = True
            confirm_reason = "Consequential action requires explicit user confirmation."

        # ASR confidence policy (Spec §32)
        # If voice confidence is low (< 0.65) on a non-trivial command, demand confirmation
        if modality == InputModality.VOICE and confidence < 0.65 and len(cleaned.split()) > 1:
            req_confirm = True
            confirm_reason = f"Low speech recognition confidence ({confidence:.0%})."

        return HarmaRequest(
            request_id=req_id,
            clean_goal=cleaned,
            raw_input=raw,
            modality=modality,
            language=lang,
            confidence=confidence,
            target_device=target_device,
            is_control_command=is_control,
            control_intent=control_intent,
            risk_level=risk,
            requires_confirmation=req_confirm,
            confirmation_reason=confirm_reason,
            metadata=meta,
        )
