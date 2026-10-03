"""
Harma Integrations & MCP — Exception Hierarchy

Typed exceptions for external service connectivity, MCP protocol operations,
credential management, schema validation, and circuit breakers.
"""

from __future__ import annotations

from typing import Any, Optional


class IntegrationError(Exception):
    """Base class for all integration and MCP errors."""

    def __init__(self, message: str, server_name: str = "", details: Optional[dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.server_name = server_name
        self.details = details or {}


class MCPServerUnavailableError(IntegrationError):
    """Raised when an MCP server is unreachable or offline."""
    pass


class MCPConnectionError(IntegrationError):
    """Raised when connection to an MCP server fails during transport handshake."""
    pass


class MCPProtocolError(IntegrationError):
    """Raised when JSON-RPC or MCP protocol violation occurs."""
    pass


class MCPTimeoutError(IntegrationError):
    """Raised when an MCP tool invocation or request exceeds the timeout."""
    pass


class MCPAuthRequiredError(IntegrationError):
    """Raised when an integration requires authentication or credentials expired."""
    pass


class SchemaValidationError(IntegrationError):
    """Raised when tool arguments fail validation against advertised inputSchema."""

    def __init__(self, message: str, tool_name: str = "", errors: Optional[list[str]] = None) -> None:
        super().__init__(message)
        self.tool_name = tool_name
        self.errors = errors or []


class IntegrationPermissionDeniedError(IntegrationError):
    """Raised when an action is blocked by Harma's permission system or task allowlist."""

    def __init__(self, message: str, tool_name: str = "", required_level: str = "") -> None:
        super().__init__(message)
        self.tool_name = tool_name
        self.required_level = required_level


class CircuitBreakerOpenError(IntegrationError):
    """Raised when calls to an integration are temporarily rejected due to circuit breaker trip."""

    def __init__(self, server_name: str, cooldown_remaining: float = 0.0) -> None:
        super().__init__(
            f"Circuit breaker is OPEN for server '{server_name}'. In cooldown for {cooldown_remaining:.1f}s.",
            server_name=server_name,
        )
        self.cooldown_remaining = cooldown_remaining


class RateLimitExceededError(IntegrationError):
    """Raised when external service rate limit (HTTP 429) is encountered."""

    def __init__(self, server_name: str, retry_after: Optional[float] = None) -> None:
        msg = f"Rate limit exceeded for '{server_name}'."
        if retry_after:
            msg += f" Retry after {retry_after:.1f}s."
        super().__init__(msg, server_name=server_name)
        self.retry_after = retry_after
