"""
Harma Integrations & MCP — Data Models

Data structures representing integration configurations, server lifecycle states,
tool metadata, normalized execution results, and health statistics.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from harma.tools.base import PermissionLevel


class ServerStatus(str, Enum):
    """Lifecycle state of an external integration/MCP server."""
    REGISTERED = "registered"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    READY = "ready"
    DISCONNECTING = "disconnecting"
    DISCONNECTED = "disconnected"
    FAILED = "failed"
    RECONNECTING = "reconnecting"


class ToolCapability(str, Enum):
    """Semantic action classification for an integration tool."""
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    SEND = "send"
    EXECUTE = "execute"
    ADMIN = "admin"


class CircuitStatus(str, Enum):
    """Circuit breaker health rating."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass
class IntegrationServerConfig:
    """Configuration definition for an external service or MCP server."""
    name: str
    transport: str = "stdio"  # "stdio", "in_memory", "http_sse"
    command: Optional[str] = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: Optional[str] = None
    timeout_seconds: float = 30.0
    allowed_tools: Optional[list[str]] = None  # None = allow all advertised
    enabled: bool = True
    auto_connect: bool = True
    headers: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "transport": self.transport,
            "command": self.command,
            "args": self.args,
            "url": self.url,
            "timeout_seconds": self.timeout_seconds,
            "allowed_tools": self.allowed_tools,
            "enabled": self.enabled,
            "auto_connect": self.auto_connect,
        }


@dataclass
class IntegrationToolDef:
    """Discovered and normalized metadata for an integration tool."""
    id: str
    name: str  # Namespaced (e.g. "github.create_issue")
    original_name: str  # Server-advertised name (e.g. "create_issue")
    server_name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    output_schema: Optional[dict[str, Any]] = None
    capability: ToolCapability = ToolCapability.READ
    permission_level: PermissionLevel = PermissionLevel.SAFE
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "original_name": self.original_name,
            "server_name": self.server_name,
            "description": self.description,
            "input_schema": self.input_schema,
            "capability": self.capability.value,
            "permission_level": self.permission_level.value,
            "enabled": self.enabled,
        }


@dataclass
class IntegrationResult:
    """Normalized output from an external service or MCP tool call."""
    success: bool
    data: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    server_name: str = ""
    tool_name: str = ""
    raw_response: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "server_name": self.server_name,
            "tool_name": self.tool_name,
        }


@dataclass
class IntegrationHealth:
    """Real-time health statistics for an external server integration."""
    server_name: str
    status: ServerStatus = ServerStatus.DISCONNECTED
    circuit_status: CircuitStatus = CircuitStatus.HEALTHY
    tool_count: int = 0
    last_success_at: Optional[float] = None
    last_failure_at: Optional[float] = None
    consecutive_failures: int = 0
    total_calls: int = 0
    failed_calls: int = 0
    error_message: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "server_name": self.server_name,
            "status": self.status.value,
            "circuit_status": self.circuit_status.value,
            "tool_count": self.tool_count,
            "last_success_at": self.last_success_at,
            "last_failure_at": self.last_failure_at,
            "consecutive_failures": self.consecutive_failures,
            "total_calls": self.total_calls,
            "failed_calls": self.failed_calls,
            "error_message": self.error_message,
        }


@dataclass
class MCPResource:
    """External resource exposed by an MCP server (e.g. github://repo/readme)."""
    uri: str
    name: str
    description: str = ""
    mime_type: Optional[str] = None
    text: Optional[str] = None
    blob: Optional[bytes] = None


@dataclass
class MCPPrompt:
    """Prompt template advertised by an MCP server."""
    name: str
    description: str = ""
    arguments: list[dict[str, Any]] = field(default_factory=list)
