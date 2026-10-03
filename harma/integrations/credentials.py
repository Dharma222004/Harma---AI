"""
Harma Integrations — Secure Credential Management & Secret Redaction

Provides isolated credential storage and pattern-based secret redaction to ensure
API keys, OAuth tokens, and secrets are never exposed in prompts, logs, memory,
or task history.
"""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Optional

from harma.config.logging_config import get_logger

log = get_logger(__name__)


@dataclass
class OAuthToken:
    """OAuth 2.0 credential state with refresh metadata."""
    access_token: str
    token_type: str = "Bearer"
    refresh_token: Optional[str] = None
    expires_at: Optional[float] = None
    scope: str = ""

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        # Buffer 30 seconds before expiration
        return time.time() >= (self.expires_at - 30.0)


class CredentialStore(ABC):
    """Abstract interface for storing and retrieving integration secrets."""

    @abstractmethod
    def get(self, key: str) -> Optional[str]:
        """Retrieve secret by key."""
        pass

    @abstractmethod
    def set(self, key: str, value: str) -> None:
        """Store secret by key."""
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Remove secret."""
        pass

    @abstractmethod
    def list_keys(self) -> list[str]:
        """List stored credential keys (never values)."""
        pass


class MemoryCredentialStore(CredentialStore):
    """In-memory secure credential store for runtime session keys."""

    def __init__(self, initial_credentials: Optional[dict[str, str]] = None) -> None:
        self._store: dict[str, str] = dict(initial_credentials or {})
        self._oauth_tokens: dict[str, OAuthToken] = {}
        self._refresh_handlers: dict[str, Callable[[str], Coroutine[Any, Any, OAuthToken]]] = {}

    def get(self, key: str) -> Optional[str]:
        return self._store.get(key)

    def set(self, key: str, value: str) -> None:
        self._store[key] = value

    def delete(self, key: str) -> bool:
        return self._store.pop(key, None) is not None

    def list_keys(self) -> list[str]:
        return list(self._store.keys())

    def get_oauth_token(self, provider: str) -> Optional[OAuthToken]:
        return self._oauth_tokens.get(provider)

    def set_oauth_token(self, provider: str, token: OAuthToken) -> None:
        self._oauth_tokens[provider] = token

    def register_refresh_handler(
        self, provider: str, handler: Callable[[str], Coroutine[Any, Any, OAuthToken]]
    ) -> None:
        self._refresh_handlers[provider] = handler

    async def get_valid_token(self, provider: str) -> Optional[str]:
        """Returns active access token, refreshing if expired and refresh handler is set."""
        token = self._oauth_tokens.get(provider)
        if not token:
            return None

        if token.is_expired and token.refresh_token and provider in self._refresh_handlers:
            log.info("OAuth token for %s expired; attempting refresh", provider)
            try:
                new_token = await self._refresh_handlers[provider](token.refresh_token)
                self._oauth_tokens[provider] = new_token
                return new_token.access_token
            except Exception as e:
                log.error("Failed to refresh OAuth token for %s: %s", provider, e)
                return None

        return token.access_token


class SecretRedactor:
    """
    Scans text or structured payloads and redacts discovered credentials,
    bearer tokens, and API key patterns.
    """

    _KNOWN_PATTERNS = [
        re.compile(r"ghp_[A-Za-z0-9_]{20,}", re.IGNORECASE),               # GitHub personal access token
        re.compile(r"gho_[A-Za-z0-9_]{20,}", re.IGNORECASE),               # GitHub OAuth access token
        re.compile(r"github_pat_[A-Za-z0-9_]{22,}", re.IGNORECASE),        # GitHub fine-grained token
        re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),      # Standard Bearer auth header
        re.compile(r"AIzaSy[A-Za-z0-9_-]{33}", re.IGNORECASE),             # Google API key
        re.compile(r"gsk_[A-Za-z0-9_]{40,}", re.IGNORECASE),               # Groq API key
        re.compile(r"sk-[A-Za-z0-9]{32,}", re.IGNORECASE),                 # OpenAI-style key
    ]

    def __init__(self, explicit_secrets: Optional[list[str]] = None) -> None:
        self.explicit_secrets: set[str] = set(explicit_secrets or [])

    def register_secret(self, secret: str) -> None:
        """Add known secret string for exact-match redaction."""
        if secret and len(secret) >= 6:
            self.explicit_secrets.add(secret)

    def redact_text(self, text: str) -> str:
        """Replace all identified secrets in text with '[REDACTED]'."""
        if not text or not isinstance(text, str):
            return text

        result = text
        # 1. Redact explicit secrets
        for secret in self.explicit_secrets:
            if secret in result:
                result = result.replace(secret, "[REDACTED]")

        # 2. Redact regex patterns
        for pattern in self._KNOWN_PATTERNS:
            result = pattern.sub("[REDACTED]", result)

        return result

    def redact_payload(self, data: Any) -> Any:
        """Recursively redact strings in dicts, lists, and strings."""
        if isinstance(data, str):
            return self.redact_text(data)
        elif isinstance(data, dict):
            return {k: self.redact_payload(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self.redact_payload(item) for item in data]
        return data


# Global singleton redactor
_redactor = SecretRedactor()


def get_secret_redactor() -> SecretRedactor:
    return _redactor
