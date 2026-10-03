"""
Harma Long-Term Memory — Privacy & Secret Detection — Phase 5

Before any memory is persisted, it passes through this module.

Two layers:
  1. SecretDetector — pattern-based scan for credentials, API keys, tokens.
     If detected → BLOCK persistence entirely.

  2. SensitivityClassifier — classify remaining memories as NORMAL / SENSITIVE.
     Sensitive memories are stored but not auto-retrieved into general context.

Design:
  Memory is NOT a credential vault.
  Secrets are NEVER stored, even if the user explicitly asks.
  A clear error is returned to the user explaining why.

Anti-prompt-injection:
  Memory content is treated as DATA, never as instructions.
  The context-injection layer wraps it in a clearly labelled section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from harma.config.logging_config import get_logger
from harma.memory.models import Memory, MemorySensitivity

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Secret patterns — BLOCK these from ever being stored
# ─────────────────────────────────────────────────────────────────────────────

_SECRET_PATTERNS: list[tuple[str, str]] = [
    # API keys
    (r'\bsk-[A-Za-z0-9_-]{20,}\b',                     "OpenAI API key"),
    (r'\bgsk_[A-Za-z0-9]{20,}\b',                      "Groq API key"),
    (r'\bAIza[A-Za-z0-9_-]{35}\b',                     "Google API key"),
    (r'\bghp_[A-Za-z0-9]{36}\b',                       "GitHub personal access token"),
    (r'\bgho_[A-Za-z0-9]{36}\b',                       "GitHub OAuth token"),
    (r'\bxoxb-[0-9]+-[A-Za-z0-9]+\b',                  "Slack bot token"),
    (r'\bBearer\s+[A-Za-z0-9\-._~+/]+=*\b',            "Bearer token"),
    # Passwords
    (r'(?i)(password|passwd|pwd)\s*[:=]\s*\S+',         "password"),
    (r'(?i)(secret|api_key|apikey|access_key)\s*[:=]\s*\S+', "secret/key"),
    (r'(?i)(token)\s*[:=]\s*[A-Za-z0-9._\-]+',         "token"),
    # Private keys
    (r'-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----', "private key"),
    # Connection strings with credentials
    (r'(?i)(mysql|postgresql|mongodb|redis)://\w+:\w+@', "database connection string"),
    # AWS
    (r'\b(AKIA|ASIA)[A-Z0-9]{16}\b',                   "AWS access key"),
]

_COMPILED_SECRETS = [
    (re.compile(pattern, re.IGNORECASE | re.DOTALL), label)
    for pattern, label in _SECRET_PATTERNS
]


# ─────────────────────────────────────────────────────────────────────────────
# Sensitivity patterns — store but mark SENSITIVE
# ─────────────────────────────────────────────────────────────────────────────

_SENSITIVE_PATTERNS: list[str] = [
    r'(?i)\b(email|phone|address|dob|date of birth)\b',
    r'(?i)\b(credit card|card number|cvv|iban|ssn)\b',
    r'(?i)\b(salary|income|bank)\b',
    r'(?i)\b(medical|diagnosis|prescription|doctor)\b',
    r'(?i)\b(passport|driver.s license|national id)\b',
]

_COMPILED_SENSITIVE = [
    re.compile(p, re.IGNORECASE)
    for p in _SENSITIVE_PATTERNS
]


# ─────────────────────────────────────────────────────────────────────────────
# Result objects
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PrivacyCheckResult:
    allowed: bool
    reason: str = ""
    detected_type: str = ""
    suggested_sensitivity: MemorySensitivity = MemorySensitivity.NORMAL


# ─────────────────────────────────────────────────────────────────────────────
# SecretDetector
# ─────────────────────────────────────────────────────────────────────────────

class SecretDetector:
    """
    Scans text for credentials and secrets.
    If found, the memory must NOT be persisted.
    """

    def scan(self, text: str) -> PrivacyCheckResult:
        """
        Returns PrivacyCheckResult(allowed=False) if a secret is detected.
        """
        for pattern, label in _COMPILED_SECRETS:
            if pattern.search(text):
                log.warning("[PRIVACY] Secret detected (%s) — BLOCKING memory persistence.", label)
                return PrivacyCheckResult(
                    allowed=False,
                    reason=f"Content appears to contain a {label}. "
                           "Harma does not store credentials or secrets.",
                    detected_type=label,
                )
        return PrivacyCheckResult(allowed=True)

    def contains_secret(self, text: str) -> bool:
        """Return True if text contains any detected credential or secret."""
        return not self.scan(text).allowed


# ─────────────────────────────────────────────────────────────────────────────
# SensitivityClassifier
# ─────────────────────────────────────────────────────────────────────────────

class SensitivityClassifier:
    """
    Classifies memory sensitivity level.
    Content containing PII patterns is elevated to SENSITIVE.
    """

    def classify(self, text: str) -> MemorySensitivity:
        for pattern in _COMPILED_SENSITIVE:
            if pattern.search(text):
                log.info("[PRIVACY] Sensitive content detected — marking SENSITIVE.")
                return MemorySensitivity.SENSITIVE
        return MemorySensitivity.NORMAL

    def is_sensitive(self, text: str) -> bool:
        """Return True if text should be classified as sensitive."""
        return self.classify(text) != MemorySensitivity.NORMAL


# ─────────────────────────────────────────────────────────────────────────────
# PrivacyFilter — combined entry point
# ─────────────────────────────────────────────────────────────────────────────

class PrivacyFilter:
    """
    Main privacy filter used by the memory manager before persisting.

    Usage:
        filter = PrivacyFilter()
        result = filter.check(memory)
        if not result.allowed:
            raise MemoryPrivacyError(result.reason)
        # else: memory.sensitivity is updated in-place
    """

    def __init__(self) -> None:
        self._secret_detector = SecretDetector()
        self._sensitivity_classifier = SensitivityClassifier()

    def check(self, memory: Memory) -> PrivacyCheckResult:
        """
        Run secret detection + sensitivity classification on a Memory.

        If secrets are found → returns allowed=False (do NOT persist).
        Otherwise → updates memory.sensitivity in-place and returns allowed=True.
        """
        # Secret detection check
        result = self._secret_detector.scan(memory.content)
        if not result.allowed:
            return result

        # Classify sensitivity (only if not already elevated by caller)
        if memory.sensitivity == MemorySensitivity.NORMAL:
            sensitivity = self._sensitivity_classifier.classify(memory.content)
            memory.sensitivity = sensitivity
            if sensitivity != MemorySensitivity.NORMAL:
                result.suggested_sensitivity = sensitivity

        return result


# ─────────────────────────────────────────────────────────────────────────────
# Prompt-injection defence for context injection
# ─────────────────────────────────────────────────────────────────────────────

_INJECTION_PATTERNS = [
    re.compile(r'(?i)(ignore|disregard|override)\s+(all\s+)?(previous\s+)?(instructions?|rules?|system)', re.DOTALL),
    re.compile(r'(?i)reveal\s+(your\s+)?(api\s+key|password|secret|token)', re.DOTALL),
    re.compile(r'(?i)act\s+as\s+(a\s+)?(different|new|unrestricted)', re.DOTALL),
    re.compile(r'(?i)jailbreak', re.DOTALL),
    re.compile(r'(?i)DAN\s+mode', re.DOTALL),
]


def sanitize_for_context(content: str) -> str:
    """
    Sanitize memory content before injecting into LLM context.

    Detects and neutralises prompt-injection attempts embedded in stored memories.
    The memory is not deleted — it is simply rendered harmless for context injection.
    """
    # Strip dangerous pseudo-system XML/HTML tags
    content = re.sub(r'</?(?:system|instructions?|prompt|admin)[^>]*>', '', content, flags=re.IGNORECASE)

    for pattern in _INJECTION_PATTERNS:
        if pattern.search(content):
            log.warning(
                "[PRIVACY] Prompt-injection pattern detected in memory content — sanitising."
            )
            content = pattern.sub("[FILTERED: content removed by safety filter]", content)
    return content
