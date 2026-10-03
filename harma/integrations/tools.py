"""
Harma Integrations — Agent Management Tools

Exposes natural language tools to the Agent Core for inspecting, connecting,
searching, and managing external MCP services.
"""

from __future__ import annotations

from typing import Any, Optional

from harma.integrations.manager import IntegrationManager, get_integration_manager
from harma.tools.base import BaseTool, PermissionLevel, ToolResult


class ListIntegrationsTool(BaseTool):
    """List all configured external integrations and their connection statuses."""

    name = "integrations.list"
    description = (
        "Lists all configured external integrations (e.g. GitHub, Calendar, Gmail) "
        "along with their status, tool count, and health."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, manager: Optional[IntegrationManager] = None) -> None:
        self._manager = manager

    @property
    def manager(self) -> IntegrationManager:
        return self._manager or get_integration_manager()

    async def execute(self, **kwargs: Any) -> ToolResult:
        servers = self.manager.list_servers()
        if not servers:
            return ToolResult(success=True, output="No external integrations configured.")

        lines = ["Connected & Configured Integrations:"]
        for s in servers:
            lines.append(
                f"  • {s.server_name}: status={s.status.upper()}, circuit={s.circuit_status.upper()}, "
                f"tools={s.tool_count}"
            )
        return ToolResult(success=True, output="\n".join(lines), data=[s.to_dict() for s in servers])


class GetIntegrationStatusTool(BaseTool):
    """Show detailed health, tool count, and latency stats for an integration."""

    name = "integrations.status"
    description = "Retrieves real-time status and health metrics for a specific external integration."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The name of the integration (e.g. 'github', 'calendar')"}
        },
        "required": ["name"],
    }

    def __init__(self, manager: Optional[IntegrationManager] = None) -> None:
        self._manager = manager

    @property
    def manager(self) -> IntegrationManager:
        return self._manager or get_integration_manager()

    async def execute(self, name: str, **kwargs: Any) -> ToolResult:
        health = self.manager.get_status(name)
        if not health:
            return ToolResult(success=False, output="", error=f"Integration '{name}' not found.")

        lines = [
            f"Integration: {health.server_name}",
            f"Status: {health.status.upper()}",
            f"Circuit Breaker: {health.circuit_status.upper()}",
            f"Available Tools: {health.tool_count}",
            f"Total Invocations: {health.total_calls} (Failed: {health.failed_calls})",
        ]
        if health.error_message:
            lines.append(f"Last Error: {health.error_message}")

        return ToolResult(success=True, output="\n".join(lines), data=health.to_dict())


class ListIntegrationToolsTool(BaseTool):
    """List all available tools provided by an external integration."""

    name = "integrations.tools"
    description = "Lists all tools provided by a connected external integration, including parameter schemas and permissions."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "server_name": {
                "type": "string",
                "description": "Optional name of the integration (e.g. 'github'). If omitted, lists all.",
            }
        },
        "required": [],
    }

    def __init__(self, manager: Optional[IntegrationManager] = None) -> None:
        self._manager = manager

    @property
    def manager(self) -> IntegrationManager:
        return self._manager or get_integration_manager()

    async def execute(self, server_name: Optional[str] = None, **kwargs: Any) -> ToolResult:
        tools = self.manager.list_tools(server_name=server_name)
        if not tools:
            msg = f"No tools available for integration '{server_name}'." if server_name else "No integration tools registered."
            return ToolResult(success=True, output=msg, data=[])

        lines = [f"Registered Tools ({len(tools)}):"]
        for t in tools:
            lines.append(f"  • {t.name} [{t.capability.value.upper()}, {t.permission_level.value}]: {t.description}")

        return ToolResult(success=True, output="\n".join(lines), data=[t.to_dict() for t in tools])


class SearchIntegrationToolsTool(BaseTool):
    """Search for relevant external tools matching user intent."""

    name = "integrations.search_tools"
    description = "Searches for relevant external integration tools matching a keyword or user request intent."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search term or intent (e.g. 'github issues', 'send email')"},
            "top_k": {"type": "integer", "description": "Maximum number of results to return", "default": 5},
        },
        "required": ["query"],
    }

    def __init__(self, manager: Optional[IntegrationManager] = None) -> None:
        self._manager = manager

    @property
    def manager(self) -> IntegrationManager:
        return self._manager or get_integration_manager()

    async def execute(self, query: str, top_k: int = 5, **kwargs: Any) -> ToolResult:
        results = self.manager.search_tools(query, top_k=top_k)
        if not results:
            return ToolResult(success=True, output=f"No integration tools found matching '{query}'.", data=[])

        lines = [f"Found {len(results)} matching integration tools:"]
        for t in results:
            lines.append(f"  • {t.name} [{t.permission_level.value}]: {t.description}")

        return ToolResult(success=True, output="\n".join(lines), data=[t.to_dict() for t in results])


class ConnectIntegrationTool(BaseTool):
    """Connect an external integration."""

    name = "integrations.connect"
    description = "Connects to a configured external MCP service or application."
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The name of the integration to connect"}
        },
        "required": ["name"],
    }

    def __init__(self, manager: Optional[IntegrationManager] = None) -> None:
        self._manager = manager

    @property
    def manager(self) -> IntegrationManager:
        return self._manager or get_integration_manager()

    async def execute(self, name: str, **kwargs: Any) -> ToolResult:
        success = await self.manager.connect_server(name)
        if success:
            health = self.manager.get_status(name)
            tool_cnt = health.tool_count if health else 0
            return ToolResult(
                success=True,
                output=f"Successfully connected to integration '{name}'. Discovered {tool_cnt} tools.",
                data={"connected": True, "server": name, "tool_count": tool_cnt},
            )
        return ToolResult(success=False, output="", error=f"Failed to connect to integration '{name}'.")


class DisconnectIntegrationTool(BaseTool):
    """Disconnect an external integration."""

    name = "integrations.disconnect"
    description = "Disconnects from an external integration and unregisters its tools."
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The name of the integration to disconnect"}
        },
        "required": ["name"],
    }

    def __init__(self, manager: Optional[IntegrationManager] = None) -> None:
        self._manager = manager

    @property
    def manager(self) -> IntegrationManager:
        return self._manager or get_integration_manager()

    async def execute(self, name: str, **kwargs: Any) -> ToolResult:
        success = await self.manager.disconnect_server(name)
        if success:
            return ToolResult(success=True, output=f"Successfully disconnected from integration '{name}'.")
        return ToolResult(success=False, output="", error=f"Could not disconnect integration '{name}'.")


def get_integration_tools(manager: Optional[IntegrationManager] = None) -> list[BaseTool]:
    """Return all management tools for the integration subsystem."""
    return [
        ListIntegrationsTool(manager),
        GetIntegrationStatusTool(manager),
        ListIntegrationToolsTool(manager),
        SearchIntegrationToolsTool(manager),
        ConnectIntegrationTool(manager),
        DisconnectIntegrationTool(manager),
    ]
