"""
Harma Integrations — Circuit Breaker & Rate Limiting

Protects external services and Harma from cascading failures, rate-limit bans (HTTP 429),
and prolonged server outages.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from harma.config.logging_config import get_logger
from harma.integrations.exceptions import CircuitBreakerOpenError, RateLimitExceededError
from harma.integrations.models import CircuitStatus

log = get_logger(__name__)


class CircuitBreaker:
    """
    State machine preventing repeated requests to failing or unresponsive external services.

    States:
      - HEALTHY (Closed): Normal operation.
      - DEGRADED (Half-Open): Testing recovery after cooldown with limited probe traffic.
      - UNAVAILABLE (Open): Temporarily rejecting requests to prevent thrashing.
    """

    def __init__(
        self,
        server_name: str,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
        success_threshold: int = 2,
    ) -> None:
        self.server_name = server_name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.success_threshold = success_threshold

        self.status = CircuitStatus.HEALTHY
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.opened_at: Optional[float] = None
        self.total_failures = 0
        self.total_successes = 0

    def check_state(self) -> None:
        """Verify circuit status before invoking external tool."""
        now = time.time()
        if self.status == CircuitStatus.UNAVAILABLE:
            elapsed = now - (self.opened_at or 0.0)
            if elapsed >= self.cooldown_seconds:
                log.info("Circuit breaker for %s transitioning to DEGRADED (half-open probe)", self.server_name)
                self.status = CircuitStatus.DEGRADED
                self.consecutive_successes = 0
            else:
                remaining = self.cooldown_seconds - elapsed
                raise CircuitBreakerOpenError(self.server_name, cooldown_remaining=remaining)

    def record_success(self) -> None:
        """Record successful invocation."""
        self.consecutive_failures = 0
        self.total_successes += 1

        if self.status == CircuitStatus.DEGRADED:
            self.consecutive_successes += 1
            if self.consecutive_successes >= self.success_threshold:
                log.info("Circuit breaker for %s recovered to HEALTHY", self.server_name)
                self.status = CircuitStatus.HEALTHY
                self.opened_at = None

    def record_failure(self, error: Exception) -> None:
        """Record failed invocation and trip breaker if threshold exceeded."""
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.total_failures += 1

        if self.consecutive_failures >= self.failure_threshold:
            if self.status != CircuitStatus.UNAVAILABLE:
                log.warning(
                    "Circuit breaker TRIPPED for %s after %d consecutive failures. Cooling down for %.1fs.",
                    self.server_name,
                    self.consecutive_failures,
                    self.cooldown_seconds,
                )
            self.status = CircuitStatus.UNAVAILABLE
            self.opened_at = time.time()

    def reset(self) -> None:
        """Force reset circuit breaker to healthy."""
        self.status = CircuitStatus.HEALTHY
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.opened_at = None


class RateLimiter:
    """
    Client-side rate-limit monitor supporting HTTP 429 Retry-After backoff
    and minimum interval pacing.
    """

    def __init__(self, server_name: str, min_interval_seconds: float = 0.0) -> None:
        self.server_name = server_name
        self.min_interval_seconds = min_interval_seconds
        self.last_call_at: float = 0.0
        self.blocked_until: Optional[float] = None
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait if rate limited or if pacing interval requires pause."""
        async with self._lock:
            now = time.time()
            if self.blocked_until and now < self.blocked_until:
                delay = self.blocked_until - now
                log.info("RateLimiter pacing call to %s for %.2fs", self.server_name, delay)
                await asyncio.sleep(delay)

            if self.min_interval_seconds > 0:
                elapsed = now - self.last_call_at
                if elapsed < self.min_interval_seconds:
                    await asyncio.sleep(self.min_interval_seconds - elapsed)

            self.last_call_at = time.time()

    def handle_rate_limit(self, retry_after: Optional[float] = None) -> None:
        """Set backoff barrier when HTTP 429 or provider rate limit is received."""
        delay = retry_after if retry_after is not None else 60.0
        self.blocked_until = time.time() + delay
        log.warning("Rate limit barrier applied for %s: backoff %.1fs", self.server_name, delay)
