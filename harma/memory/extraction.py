"""
Harma Long-Term Memory — Extraction Pipeline — Phase 5

Analyses conversations to identify candidate memories worth persisting.

Rules:
  - Explicit user statements ("Remember that…", "My project is…") → high confidence
  - Inferred repetition → lower confidence, not auto-saved without confirmation
  - Temporary queries ("What is Python?", "Open Chrome") → NOT extracted
  - Secrets → blocked by PrivacyFilter before this layer

Pipeline:
    conversation_turn
        → rule-based pattern extraction (fast, local)
        → candidate generation
        → privacy filter
        → importance / confidence scoring
        → return candidates (caller decides to persist or not)

Design:
  This module does NOT persist anything directly.
  It returns MemoryCandidate objects.
  The MemoryManager decides what to save based on configuration.
"""

from __future__ import annotations

import re
from typing import Optional

from harma.config.logging_config import get_logger
from harma.memory.models import (
    MemoryCandidate, MemorySource, MemoryType, MemorySensitivity,
)
from harma.memory.privacy import PrivacyFilter

log = get_logger(__name__)

# ── Patterns for explicit memory triggers ─────────────────────────────────────

# "Remember that X", "Remember: X"
_REMEMBER_PATTERNS = [
    re.compile(r'(?i)^remember\s+that\s+(.+)$'),
    re.compile(r'(?i)^remember[,:]?\s+(.+)$'),
    re.compile(r'(?i)^please\s+remember\s+(?:that\s+)?(.+)$'),
    re.compile(r'(?i)^note\s+that\s+(.+)$'),
    re.compile(r'(?i)^keep\s+in\s+mind\s+that\s+(.+)$'),
]

# "My X is Y" / "I use X" / "I prefer X" patterns
_PREFERENCE_PATTERNS = [
    re.compile(r'(?i)my\s+(?:preferred?\s+)?(?:programming\s+)?language\s+is\s+(.+?)[\.,]?$'),
    re.compile(r'(?i)i\s+(?:prefer|use|like)\s+(.+?)\s+(?:for|as|over|instead)'),
    re.compile(r'(?i)^i\s+(?:prefer|use|like)\s+(.+?)[\.,]?$'),
    re.compile(r'(?i)my\s+(?:main\s+|primary\s+)?(?:editor|ide|tool)\s+is\s+(.+?)[\.,]?$'),
    re.compile(r'(?i)i\s+(?:prefer|like)\s+(.+?)\s+(?:responses?|style|format)'),
]

# "My project is X" / "I'm working on X"
_PROJECT_PATTERNS = [
    re.compile(r'(?i)my\s+(?:main\s+|current\s+|primary\s+)?project\s+(?:is\s+called|name\s+is|is)\s+(?:called\s+)?(.+?)[\.,]?$'),
    re.compile(r'(?i)(?:the|my)\s+project(?:\s+is)?\s+(?:called|named)\s+(.+?)[\.,]?$'),
    re.compile(r'(?i)i(?:\'m|\s+am)\s+working\s+on\s+(?:a\s+project\s+called\s+)?(.+?)[\.,]?$'),
    re.compile(r'(?i)(?:the|my)\s+(?:app|application|system|repo|repository)\s+is\s+(?:called\s+)?(.+?)[\.,]?$'),
]

# Patterns for user corrections
_CORRECTION_PATTERNS = [
    re.compile(r'(?i)i\s+(?:don\'t|do not|no longer|stopped?)\s+use\s+(.+?)[\.,]?$'),
    re.compile(r'(?i)i\s+now\s+use\s+(.+?)[\.,]?$'),
    re.compile(r'(?i)(?:actually|correction)[,:]?\s+(.+)$'),
    re.compile(r'(?i)i\s+(?:switched?|moved?|changed?)\s+(?:to|from)\s+(.+?)[\.,]?$'),
    re.compile(r'(?i)(?:update|change|correct)\s+(?:that|it)[,:]?\s+(.+)$'),
]

# Temporary / skip patterns — do NOT extract these
_SKIP_PATTERNS = [
    re.compile(r'(?i)^(?:what|who|where|when|how|why)\s+is\b'),
    re.compile(r'(?i)^(?:open|close|launch|start|stop)\s+\w+$'),
    re.compile(r'(?i)^(?:search|find|look)\s+(?:for|up)\b'),
    re.compile(r'(?i)^(?:what(?:\'s)?|tell me)\s+(?:the\s+)?(?:time|date|weather|news)\b'),
    re.compile(r'(?i)^(?:ok|okay|yes|no|sure|thanks|thank you|bye|goodbye)\s*$'),
    re.compile(r'(?i)^(?:help|hello|hi)\s*$'),
]


def _should_skip(text: str) -> bool:
    """Return True if this message should never be extracted as a memory."""
    text = text.strip()
    # Short messages are not worth extracting (less than 6 characters)
    if len(text) < 6:
        return True
    for pattern in _SKIP_PATTERNS:
        if pattern.search(text):
            return True
    return False


class MemoryExtractor:
    """
    Analyses user utterances and identifies candidate long-term memories.

    Does NOT persist anything — returns candidates only.
    Explicit triggers (remember, my project is, etc.) produce high-confidence candidates.
    Does NOT auto-generate candidates from casual conversation.
    """

    def __init__(self) -> None:
        self._privacy = PrivacyFilter()

    def extract(
        self,
        user_text: str,
        project_id: Optional[str] = None,
    ) -> list[MemoryCandidate]:
        """
        Extract candidate memories from a user utterance.

        Args:
            user_text: The user's message.
            project_id: Active project context, if any.

        Returns:
            List of MemoryCandidate objects (may be empty).
        """
        text = user_text.strip()
        if not text or _should_skip(text):
            return []

        candidates: list[MemoryCandidate] = []

        # ── 1. Explicit "remember that" triggers ──────────────────────────────
        for pattern in _REMEMBER_PATTERNS:
            m = pattern.match(text)
            if m:
                content = m.group(1).strip().rstrip(".")
                if content:
                    candidates.append(MemoryCandidate(
                        content=content,
                        memory_type=MemoryType.SEMANTIC,
                        source=MemorySource.EXPLICIT_USER,
                        importance=0.8,
                        confidence=1.0,
                        tags=self._auto_tags(content),
                        project_id=project_id,
                    ))
                break  # only one "remember" pattern per turn

        # ── 2. Preference patterns ────────────────────────────────────────────
        if not candidates:
            for pattern in _PREFERENCE_PATTERNS:
                m = pattern.search(text)
                if m:
                    content = text.strip().rstrip(".")
                    candidates.append(MemoryCandidate(
                        content=content,
                        memory_type=MemoryType.PREFERENCE,
                        source=MemorySource.EXPLICIT_USER,
                        importance=0.75,
                        confidence=0.95,
                        tags=self._auto_tags(content),
                        project_id=project_id,
                    ))
                    break

        # ── 3. Project patterns ───────────────────────────────────────────────
        if not candidates:
            for pattern in _PROJECT_PATTERNS:
                m = pattern.search(text)
                if m:
                    content = text.strip().rstrip(".")
                    # Extract the project name for project_id
                    proj_name = m.group(1).strip().rstrip(".").lower()
                    candidates.append(MemoryCandidate(
                        content=content,
                        memory_type=MemoryType.PROJECT,
                        source=MemorySource.EXPLICIT_USER,
                        importance=0.85,
                        confidence=1.0,
                        tags=self._auto_tags(content) + ["project"],
                        project_id=project_id or proj_name,
                    ))
                    break

        # ── 4. Correction patterns ────────────────────────────────────────────
        if not candidates:
            for pattern in _CORRECTION_PATTERNS:
                m = pattern.search(text)
                if m:
                    content = text.strip().rstrip(".")
                    candidates.append(MemoryCandidate(
                        content=content,
                        memory_type=MemoryType.PREFERENCE,
                        source=MemorySource.USER_CORRECTION,
                        importance=0.9,
                        confidence=1.0,
                        tags=self._auto_tags(content),
                        project_id=project_id,
                    ))
                    break

        # ── Privacy filter each candidate ─────────────────────────────────────
        safe_candidates = []
        for candidate in candidates:
            # Build a temporary Memory for privacy check
            mem = candidate.to_memory()
            result = self._privacy.check(mem)
            if result.allowed:
                # Update sensitivity from the privacy filter
                candidate.sensitivity = mem.sensitivity
                safe_candidates.append(candidate)
            else:
                log.warning(
                    "[EXTRACT] Candidate rejected by privacy filter: %s",
                    result.reason,
                )

        if safe_candidates:
            log.info(
                "[EXTRACT] Extracted %d candidate(s) from: %r",
                len(safe_candidates), text[:60],
            )

        return safe_candidates

    def _auto_tags(self, content: str) -> list[str]:
        """Generate automatic tags from content for better searchability."""
        # Simple word-frequency approach: extract nouns-like tokens
        words = re.findall(r'\b[A-Za-z][A-Za-z0-9]+\b', content)
        # Filter common short/stop words
        skip = {
            "my", "the", "is", "are", "use", "for", "in", "and",
            "or", "not", "that", "this", "of", "to", "a", "I",
        }
        tags = list({w.lower() for w in words if w.lower() not in skip and len(w) > 2})
        return tags[:5]  # max 5 auto-tags
