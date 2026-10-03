"""
Harma Task Retry & Error Classification

Classifies execution errors into transient vs. permanent and computes backoff delays.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class ErrorCategory(str, Enum):
    TRANSIENT_ERROR = "transient_error"
    PERMANENT_ERROR = "permanent_error"
    PERMISSION_ERROR = "permission_error"
    AUTHENTICATION_ERROR = "authentication_error"
    USER_ACTION_REQUIRED = "user_action_required"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    TOOL_ERROR = "tool_error"
    UNKNOWN_ERROR = "unknown_error"


class ErrorClassifier:
    """Classifies errors to determine whether an automatic retry is safe."""

    @staticmethod
    def classify(error: Exception | str) -> ErrorCategory:
        err_msg = str(error).lower()

        # Non-retryable security / permissions
        if any(term in err_msg for term in ["permission", "scope_violation", "unauthorized", "forbidden"]):
            return ErrorCategory.PERMISSION_ERROR

        if any(term in err_msg for term in ["pin", "password", "biometric", "captcha", "device_locked"]):
            return ErrorCategory.AUTHENTICATION_ERROR

        if any(term in err_msg for term in ["user action required", "needs_confirmation", "confirmation required"]):
            return ErrorCategory.USER_ACTION_REQUIRED

        # Rate limits
        if any(term in err_msg for term in ["rate limit", "429", "too many requests", "resource exhausted"]):
            return ErrorCategory.RATE_LIMIT

        # Timeouts & network
        if any(term in err_msg for term in ["timeout", "timed out", "connection reset", "network", "temporary"]):
            return ErrorCategory.TRANSIENT_ERROR

        # Permanent
        if any(term in err_msg for term in ["not found", "syntax", "invalid", "app_not_found"]):
            return ErrorCategory.PERMANENT_ERROR

        return ErrorCategory.UNKNOWN_ERROR

    @staticmethod
    def is_retryable(category: ErrorCategory) -> bool:
        """Only transient errors, rate limits, and timeouts are safe to retry."""
        return category in (
            ErrorCategory.TRANSIENT_ERROR,
            ErrorCategory.RATE_LIMIT,
            ErrorCategory.TIMEOUT,
        )


class RetryPolicy:
    """Calculates backoff delays for retryable task attempts."""

    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay_seconds: float = 2.0,
        backoff_factor: float = 2.0,
        max_delay_seconds: float = 300.0,
    ) -> None:
        self.max_attempts = max_attempts
        self.initial_delay_seconds = initial_delay_seconds
        self.backoff_factor = backoff_factor
        self.max_delay_seconds = max_delay_seconds

    def should_retry(self, attempt_count: int, error: Exception | str) -> bool:
        if attempt_count >= self.max_attempts:
            return False
        category = ErrorClassifier.classify(error)
        return ErrorClassifier.is_retryable(category)

    def compute_backoff(self, attempt_count: int) -> float:
        delay = self.initial_delay_seconds * (self.backoff_factor ** max(0, attempt_count - 1))
        return min(delay, self.max_delay_seconds)
