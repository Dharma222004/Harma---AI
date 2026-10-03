"""
Harma Integrations — Integration Registry

Tracks discovered external tools, normalizes their schemas and permission levels,
and registers them dynamically into Harma's native ToolRegistry.
"""

from __future__ import annotations

from typing import Optional

from harma.config.logging_config import get_logger
from harma.integrations.circuit_breaker import CircuitBreaker, RateLimiter
from harma.integrations.mcp.adapter import MCPToolAdapter
from harma.integrations.mcp.client import MCPClient
from harma.integrations.models import IntegrationServerConfig, IntegrationToolDef, ToolCapability
from harma.integrations.permissions import IntegrationPermissionPolicy
from harma.tools.base import PermissionLevel
from harma.tools.registry import ToolRegistry

log = get_logger(__name__)


class IntegrationRegistry:
    """
    Manages external tools across all active integrations and coordinates
    dynamic insertion/removal into the Agent Core's ToolRegistry.
    """

    def __init__(self, tool_registry: Optional[ToolRegistry] = None) -> None:
        self.tool_registry = tool_registry if tool_registry is not None else ToolRegistry()
        self._tools: dict[str, IntegrationToolDef] = {}  # namespaced_name -> def
        self._server_tools: dict[str, set[str]] = {}     # server_name -> set of namespaced_names

    def register_server_tools(
        self,
        config: IntegrationServerConfig,
        client: MCPClient,
        advertised_tools: list[dict],
        circuit_breaker: Optional[CircuitBreaker] = None,
        rate_limiter: Optional[RateLimiter] = None,
        dry_run: bool = False,
    ) -> list[IntegrationToolDef]:
        """
        Normalize and mount discovered MCP tools into the central ToolRegistry.
        """
        server_name = config.name
        self._server_tools.setdefault(server_name, set())
        registered_defs: list[IntegrationToolDef] = []

        for raw in advertised_tools:
            orig_name = raw.get("name", "")
            if not orig_name:
                continue

            if orig_name.startswith(f"{server_name}."):
                namespaced_name = orig_name
            else:
                namespaced_name = f"{server_name}.{orig_name}"

            # Check server-level tool allowlist
            if config.allowed_tools is not None and namespaced_name not in config.allowed_tools and orig_name not in config.allowed_tools:
                log.info("Tool '%s' skipped by server allowlist for '%s'", namespaced_name, server_name)
                continue

            description = raw.get("description", "")
            input_schema = raw.get("inputSchema", {"type": "object", "properties": {}})

            # Infer capability and authoritative permission level
            capability = IntegrationPermissionPolicy.infer_capability(namespaced_name, description)
            permission_level = IntegrationPermissionPolicy.determine_permission_level(
                namespaced_name, capability=capability, description=description
            )

            tool_def = IntegrationToolDef(
                id=f"{server_name}_{orig_name}",
                name=namespaced_name,
                original_name=orig_name,
                server_name=server_name,
                description=description,
                input_schema=input_schema,
                capability=capability,
                permission_level=permission_level,
                enabled=config.enabled,
            )

            # Create BaseTool adapter and register with central ToolRegistry
            adapter = MCPToolAdapter(
                tool_def=tool_def,
                client=client,
                circuit_breaker=circuit_breaker,
                rate_limiter=rate_limiter,
                timeout_seconds=config.timeout_seconds,
                dry_run=dry_run,
            )

            self.tool_registry.register(adapter)
            self._tools[namespaced_name] = tool_def
            self._server_tools[server_name].add(namespaced_name)
            registered_defs.append(tool_def)
            log.info("Registered external tool: %s (%s, %s)", namespaced_name, capability.value, permission_level.value)

        return registered_defs

    def unregister_server_tools(self, server_name: str) -> int:
        """Remove all tools associated with a server from the ToolRegistry."""
        tool_names = self._server_tools.pop(server_name, set())
        removed_count = 0
        for name in tool_names:
            if name in self._tools:
                del self._tools[name]
            if name in self.tool_registry._tools:
                del self.tool_registry._tools[name]
                removed_count += 1
        log.info("Unregistered %d tools for server '%s'", removed_count, server_name)
        return removed_count

    def get_tool_def(self, namespaced_name: str) -> Optional[IntegrationToolDef]:
        return self._tools.get(namespaced_name)

    def list_tools(
        self,
        server_name: Optional[str] = None,
        capability: Optional[ToolCapability] = None,
        permission_level: Optional[PermissionLevel] = None,
    ) -> list[IntegrationToolDef]:
        """List active integration tools with optional filtering."""
        results = list(self._tools.values())
        if server_name:
            results = [t for t in results if t.server_name == server_name]
        if capability:
            results = [t for t in results if t.capability == capability]
        if permission_level:
            results = [t for t in results if t.permission_level == permission_level]
        return results
