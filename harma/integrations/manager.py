"""
Harma Integrations — Central Integration Manager

Coordinates external server lifecycles, MCP clients, transport binding, tool discovery,
health monitoring, credential resolution, and circuit breaker governance.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from harma.config.logging_config import get_logger
from harma.integrations.circuit_breaker import CircuitBreaker, RateLimiter
from harma.integrations.credentials import CredentialStore, MemoryCredentialStore
from harma.integrations.discovery import ToolSearchEngine
from harma.integrations.exceptions import (
    MCPServerUnavailableError,
    SchemaValidationError,
)
from harma.integrations.mcp.client import MCPClient
from harma.integrations.mcp.transport import (
    InMemoryTransport,
    MCPTransport,
    StdioTransport,
)
from harma.integrations.models import (
    CircuitStatus,
    IntegrationHealth,
    IntegrationResult,
    IntegrationServerConfig,
    IntegrationToolDef,
    ServerStatus,
)
from harma.integrations.registry import IntegrationRegistry
from harma.tools.registry import ToolRegistry

log = get_logger(__name__)


class IntegrationManager:
    """Central lifecycle coordinator and tool manager for all Harma integrations."""

    def __init__(
        self,
        tool_registry: Optional[ToolRegistry] = None,
        credential_store: Optional[CredentialStore] = None,
        dry_run: bool = False,
    ) -> None:
        self.tool_registry = tool_registry if tool_registry is not None else ToolRegistry()
        self.registry = IntegrationRegistry(tool_registry=self.tool_registry)
        self.credential_store = credential_store or MemoryCredentialStore()
        self.search_engine = ToolSearchEngine(registry=self.registry)
        self.dry_run = dry_run

        self.configs: dict[str, IntegrationServerConfig] = {}
        self.clients: dict[str, MCPClient] = {}
        self.transports: dict[str, MCPTransport] = {}
        self.statuses: dict[str, ServerStatus] = {}
        self.circuit_breakers: dict[str, CircuitBreaker] = {}
        self.rate_limiters: dict[str, RateLimiter] = {}
        self.health_stats: dict[str, IntegrationHealth] = {}

    def register_server(
        self,
        config: IntegrationServerConfig,
        custom_transport: Optional[MCPTransport] = None,
    ) -> None:
        """Register server configuration and initialize health tracking."""
        name = config.name
        self.configs[name] = config
        self.statuses[name] = ServerStatus.REGISTERED
        self.circuit_breakers[name] = CircuitBreaker(server_name=name)
        self.rate_limiters[name] = RateLimiter(server_name=name)
        self.health_stats[name] = IntegrationHealth(server_name=name, status=ServerStatus.REGISTERED)

        if custom_transport:
            self.transports[name] = custom_transport

        log.info("Registered external integration: '%s' (transport=%s)", name, config.transport)

    async def connect_server(self, name: str) -> bool:
        """Establish connection to an MCP server, discover tools, and register them."""
        config = self.configs.get(name)
        if not config:
            log.error("Cannot connect unknown integration '%s'", name)
            return False

        if not config.enabled:
            log.warning("Integration '%s' is disabled. Enable it first.", name)
            return False

        self.statuses[name] = ServerStatus.CONNECTING
        self.health_stats[name].status = ServerStatus.CONNECTING

        try:
            # 1. Resolve or create transport
            transport = self.transports.get(name)
            if not transport:
                if config.transport == "stdio" and config.command:
                    # Inject credentials into env if present
                    env = dict(config.env)
                    transport = StdioTransport(command=config.command, args=config.args, env=env)
                elif config.transport == "in_memory":
                    transport = InMemoryTransport()
                else:
                    raise MCPServerUnavailableError(
                        f"Unsupported or missing transport config for '{name}'", server_name=name
                    )
                self.transports[name] = transport

            # 2. Instantiate and connect MCPClient
            client = MCPClient(
                transport=transport,
                server_name=name,
                timeout_seconds=config.timeout_seconds,
            )
            self.clients[name] = client

            await client.initialize()
            self.statuses[name] = ServerStatus.CONNECTED
            self.health_stats[name].status = ServerStatus.CONNECTED

            # 3. Discover tools
            raw_tools = await client.list_tools()
            self.circuit_breakers[name].record_success()

            # 4. Mount into IntegrationRegistry & ToolRegistry
            tool_defs = self.registry.register_server_tools(
                config=config,
                client=client,
                advertised_tools=raw_tools,
                circuit_breaker=self.circuit_breakers[name],
                rate_limiter=self.rate_limiters[name],
                dry_run=self.dry_run,
            )

            self.statuses[name] = ServerStatus.READY
            health = self.health_stats[name]
            health.status = ServerStatus.READY
            health.tool_count = len(tool_defs)
            health.last_success_at = time.time()
            health.error_message = None

            log.info("Integration '%s' is READY with %d tools mounted.", name, len(tool_defs))
            return True

        except Exception as e:
            log.error("Failed to connect integration '%s': %s", name, e)
            self.statuses[name] = ServerStatus.FAILED
            health = self.health_stats[name]
            health.status = ServerStatus.FAILED
            health.last_failure_at = time.time()
            health.consecutive_failures += 1
            health.error_message = str(e)
            self.circuit_breakers[name].record_failure(e)
            return False

    async def disconnect_server(self, name: str) -> bool:
        """Disconnect server and remove mounted tools from ToolRegistry."""
        if name not in self.configs:
            return False

        self.statuses[name] = ServerStatus.DISCONNECTING
        client = self.clients.pop(name, None)
        if client:
            try:
                await client.close()
            except Exception as e:
                log.warning("Error closing MCP client '%s': %s", name, e)

        # Unregister tools
        self.registry.unregister_server_tools(name)

        self.statuses[name] = ServerStatus.DISCONNECTED
        health = self.health_stats[name]
        health.status = ServerStatus.DISCONNECTED
        health.tool_count = 0
        log.info("Disconnected integration '%s'.", name)
        return True

    async def restart_server(self, name: str) -> bool:
        """Disconnect and reconnect an integration."""
        await self.disconnect_server(name)
        return await self.connect_server(name)

    async def enable_server(self, name: str, connect_immediately: bool = True) -> bool:
        """Enable an integration and optionally connect."""
        config = self.configs.get(name)
        if not config:
            return False
        config.enabled = True
        if connect_immediately:
            return await self.connect_server(name)
        return True

    async def disable_server(self, name: str) -> bool:
        """Disable and disconnect an integration."""
        config = self.configs.get(name)
        if not config:
            return False
        config.enabled = False
        await self.disconnect_server(name)
        return True

    def get_status(self, name: str) -> Optional[IntegrationHealth]:
        """Fetch real-time health and status for an integration."""
        health = self.health_stats.get(name)
        if health and name in self.circuit_breakers:
            health.circuit_status = self.circuit_breakers[name].status
        return health

    def list_servers(self) -> list[IntegrationHealth]:
        """List health stats for all registered integrations."""
        results = []
        for name in self.configs:
            h = self.get_status(name)
            if h:
                results.append(h)
        return results

    def list_tools(self, server_name: Optional[str] = None) -> list[IntegrationToolDef]:
        """List active integration tools."""
        return self.registry.list_tools(server_name=server_name)

    def search_tools(self, query: str, server_name: Optional[str] = None, top_k: int = 5) -> list[IntegrationToolDef]:
        """Dynamically find relevant tools matching query."""
        return self.search_engine.find_relevant_tools(query, server_name=server_name, top_k=top_k)

    async def call_tool(self, namespaced_name: str, arguments: dict[str, Any]) -> IntegrationResult:
        """Directly invoke a registered integration tool through its adapter."""
        tool = self.tool_registry.get(namespaced_name)
        if not tool:
            return IntegrationResult(
                success=False,
                error=f"Integration tool '{namespaced_name}' not found or server offline",
                server_name=namespaced_name.split(".")[0] if "." in namespaced_name else "",
                tool_name=namespaced_name,
            )

        start = time.time()
        res = await tool.execute(**arguments)
        duration_ms = (time.time() - start) * 1000.0

        server_name = namespaced_name.split(".")[0] if "." in namespaced_name else ""
        if server_name in self.health_stats:
            health = self.health_stats[server_name]
            health.total_calls += 1
            if not res.success:
                health.failed_calls += 1

        return IntegrationResult(
            success=res.success,
            data=res.data or res.output,
            error=res.error,
            duration_ms=duration_ms,
            server_name=server_name,
            tool_name=namespaced_name,
        )

    async def shutdown(self) -> None:
        """Gracefully disconnect all active integration clients."""
        log.info("Shutting down all active integration clients...")
        server_names = list(self.clients.keys())
        for name in server_names:
            await self.disconnect_server(name)


# ── Global Singleton Pattern ──────────────────────────────────────────────────

_global_integration_manager: Optional[IntegrationManager] = None


def get_integration_manager() -> IntegrationManager:
    global _global_integration_manager
    if _global_integration_manager is None:
        _global_integration_manager = IntegrationManager()
    return _global_integration_manager


def set_integration_manager(manager: IntegrationManager) -> None:
    global _global_integration_manager
    _global_integration_manager = manager


def reset_integration_manager() -> None:
    global _global_integration_manager
    _global_integration_manager = None
