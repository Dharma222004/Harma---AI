"""
Harma MCP — Client Implementation

Client interface managing initialization handshakes, tool discovery, tool execution,
resource retrieval, and health pings over an abstract MCPTransport.
"""

from __future__ import annotations

import asyncio
import itertools
from typing import Any, Optional

from harma.config.logging_config import get_logger
from harma.integrations.exceptions import (
    MCPAuthRequiredError,
    MCPConnectionError,
    MCPProtocolError,
    MCPServerUnavailableError,
    MCPTimeoutError,
)
from harma.integrations.mcp.protocol import (
    CLIENT_NAME,
    CLIENT_VERSION,
    MCP_PROTOCOL_VERSION,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
)
from harma.integrations.mcp.transport import MCPTransport

log = get_logger(__name__)


class MCPClient:
    """Standard Model Context Protocol client session."""

    def __init__(
        self,
        transport: MCPTransport,
        server_name: str = "mcp_server",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.transport = transport
        self.server_name = server_name
        self.timeout_seconds = timeout_seconds
        self._id_counter = itertools.count(1)
        self.server_info: dict[str, Any] = {}
        self.capabilities: dict[str, Any] = {}
        self._initialized: bool = False

    @property
    def is_ready(self) -> bool:
        return self.transport.is_connected and self._initialized

    async def connect(self) -> None:
        """Establish transport connection."""
        if not self.transport.is_connected:
            await self.transport.connect()

    async def initialize(self) -> dict[str, Any]:
        """Perform MCP initialize handshake and send initialized notification."""
        await self.connect()

        init_params = {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "roots": {"listChanged": True},
                "sampling": {},
            },
            "clientInfo": {
                "name": CLIENT_NAME,
                "version": CLIENT_VERSION,
            },
        }

        resp = await self._send_request("initialize", init_params)
        if resp.error:
            raise MCPProtocolError(
                f"Initialization failed for '{self.server_name}': {resp.error.message}",
                server_name=self.server_name,
            )

        result = resp.result or {}
        self.server_info = result.get("serverInfo", {})
        self.capabilities = result.get("capabilities", {})

        # Send initialized notification
        await self.transport.send(JSONRPCNotification(method="notifications/initialized"))
        self._initialized = True
        log.info("MCP client initialized with '%s' (protocol %s)", self.server_name, result.get("protocolVersion"))
        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        """Discover tools advertised by the MCP server."""
        resp = await self._send_request("tools/list", {})
        if resp.error:
            raise MCPProtocolError(f"Failed to list tools: {resp.error.message}", server_name=self.server_name)
        result = resp.result or {}
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Execute tool on the MCP server."""
        params = {"name": name, "arguments": arguments or {}}
        resp = await self._send_request("tools/call", params)

        if resp.error:
            # Check for auth required error codes/messages
            msg = resp.error.message
            if "auth" in msg.lower() or "unauthorized" in msg.lower() or resp.error.code == 401:
                raise MCPAuthRequiredError(f"Authentication required for {self.server_name}: {msg}", server_name=self.server_name)
            raise MCPProtocolError(f"Tool execution failed for '{name}': {msg}", server_name=self.server_name)

        return resp.result or {}

    async def list_resources(self) -> list[dict[str, Any]]:
        """Retrieve list of available resources."""
        resp = await self._send_request("resources/list", {})
        if resp.error:
            raise MCPProtocolError(f"Failed to list resources: {resp.error.message}", server_name=self.server_name)
        return (resp.result or {}).get("resources", [])

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """Read resource content by URI."""
        resp = await self._send_request("resources/read", {"uri": uri})
        if resp.error:
            raise MCPProtocolError(f"Failed to read resource '{uri}': {resp.error.message}", server_name=self.server_name)
        return resp.result or {}

    async def list_prompts(self) -> list[dict[str, Any]]:
        """List advertised prompt templates."""
        resp = await self._send_request("prompts/list", {})
        if resp.error:
            raise MCPProtocolError(f"Failed to list prompts: {resp.error.message}", server_name=self.server_name)
        return (resp.result or {}).get("prompts", [])

    async def get_prompt(self, name: str, arguments: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Get rendered prompt template."""
        resp = await self._send_request("prompts/get", {"name": name, "arguments": arguments or {}})
        if resp.error:
            raise MCPProtocolError(f"Failed to get prompt '{name}': {resp.error.message}", server_name=self.server_name)
        return resp.result or {}

    async def ping(self) -> bool:
        """Send ping request to verify server liveness."""
        try:
            resp = await self._send_request("ping", {})
            return resp.error is None
        except Exception:
            return False

    async def close(self) -> None:
        """Close connection and reset session."""
        self._initialized = False
        await self.transport.close()

    async def _send_request(self, method: str, params: Optional[dict[str, Any]] = None) -> JSONRPCResponse:
        """Send JSON-RPC request and wait for corresponding response with timeout."""
        if not self.transport.is_connected:
            raise MCPServerUnavailableError(f"Server '{self.server_name}' is not connected", server_name=self.server_name)

        req_id = next(self._id_counter)
        req = JSONRPCRequest(id=req_id, method=method, params=params)

        try:
            await self.transport.send(req)
            # Await response
            raw_msg = await asyncio.wait_for(self.transport.receive(), timeout=self.timeout_seconds)
            if raw_msg is None:
                raise MCPServerUnavailableError(f"Connection closed by server '{self.server_name}'", server_name=self.server_name)
            if not isinstance(raw_msg, JSONRPCResponse):
                raise MCPProtocolError(f"Expected JSONRPCResponse, received {type(raw_msg)}", server_name=self.server_name)
            return raw_msg
        except asyncio.TimeoutError as e:
            raise MCPTimeoutError(
                f"Request to '{self.server_name}' ({method}) timed out after {self.timeout_seconds}s",
                server_name=self.server_name,
            ) from e
        except MCPConnectionError as e:
            raise MCPServerUnavailableError(f"Transport error connecting to '{self.server_name}': {e}", server_name=self.server_name) from e
