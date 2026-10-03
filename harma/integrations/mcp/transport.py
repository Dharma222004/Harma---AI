"""
Harma MCP — Transport Abstraction

Provides transport channels for communicating with MCP servers:
  1. MCPTransport: Abstract base transport
  2. InMemoryTransport: Fast, zero-overhead in-process queue transport for unit & mock testing
  3. StdioTransport: Subprocess pipe transport (stdin/stdout) for external CLI MCP servers
  4. HttpSSETransport: HTTP/SSE transport for remote network MCP servers
"""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any, Optional, Union

from harma.config.logging_config import get_logger
from harma.integrations.exceptions import MCPConnectionError
from harma.integrations.mcp.protocol import (
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
)

log = get_logger(__name__)


class MCPTransport(ABC):
    """Abstract communication channel for exchanging JSON-RPC messages with an MCP server."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish transport channel."""
        pass

    @abstractmethod
    async def send(self, message: Union[JSONRPCRequest, JSONRPCNotification]) -> None:
        """Transmit message to server."""
        pass

    @abstractmethod
    async def receive(self) -> Optional[Union[JSONRPCResponse, JSONRPCNotification, JSONRPCRequest]]:
        """Receive message from server."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Gracefully terminate transport."""
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether transport is open and ready."""
        pass


class InMemoryTransport(MCPTransport):
    """
    Bidirectional in-memory queue transport linking an MCP client to an in-process MCP server.
    Extremely fast and deterministic for tests.
    """

    def __init__(self, incoming_queue: Optional[asyncio.Queue] = None, outgoing_queue: Optional[asyncio.Queue] = None) -> None:
        self.incoming: asyncio.Queue[str] = incoming_queue or asyncio.Queue()
        self.outgoing: asyncio.Queue[str] = outgoing_queue or asyncio.Queue()
        self._connected: bool = False

    @classmethod
    def create_pair(cls) -> tuple[InMemoryTransport, InMemoryTransport]:
        """Create a linked pair of client and server transports."""
        q1: asyncio.Queue[str] = asyncio.Queue()
        q2: asyncio.Queue[str] = asyncio.Queue()
        client_transport = cls(incoming_queue=q1, outgoing_queue=q2)
        server_transport = cls(incoming_queue=q2, outgoing_queue=q1)
        return client_transport, server_transport

    async def connect(self) -> None:
        self._connected = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def send(self, message: Union[JSONRPCRequest, JSONRPCNotification]) -> None:
        if not self._connected:
            raise MCPConnectionError("InMemoryTransport is not connected")
        await self.outgoing.put(message.serialize())

    async def receive(self) -> Optional[Union[JSONRPCResponse, JSONRPCNotification, JSONRPCRequest]]:
        if not self._connected:
            return None
        try:
            raw = await self.incoming.get()
            data = json.loads(raw)
            if "method" in data:
                if "id" in data:
                    return JSONRPCRequest(id=data["id"], method=data["method"], params=data.get("params"))
                return JSONRPCNotification(method=data["method"], params=data.get("params"))
            return JSONRPCResponse.from_dict(data)
        except asyncio.CancelledError:
            raise

    async def close(self) -> None:
        self._connected = False


class StdioTransport(MCPTransport):
    """Subprocess stdio transport communicating via newline-delimited JSON-RPC over stdin/stdout."""

    def __init__(self, command: str, args: Optional[list[str]] = None, env: Optional[dict[str, str]] = None) -> None:
        self.command = command
        self.args = args or []
        self.env = env
        self.process: Optional[asyncio.subprocess.Process] = None
        self._connected: bool = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self.process is not None and self.process.returncode is None

    async def connect(self) -> None:
        try:
            full_cmd = [self.command] + self.args
            log.info("Launching MCP stdio process: %s", " ".join(full_cmd))
            self.process = await asyncio.create_subprocess_exec(
                *full_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.env,
            )
            self._connected = True
        except Exception as e:
            self._connected = False
            raise MCPConnectionError(f"Failed to launch stdio MCP process '{self.command}': {e}") from e

    async def send(self, message: Union[JSONRPCRequest, JSONRPCNotification]) -> None:
        if not self.is_connected or not self.process or not self.process.stdin:
            raise MCPConnectionError("Stdio transport is not connected")
        payload = message.serialize() + "\n"
        self.process.stdin.write(payload.encode("utf-8"))
        await self.process.stdin.drain()

    async def receive(self) -> Optional[Union[JSONRPCResponse, JSONRPCNotification, JSONRPCRequest]]:
        if not self.is_connected or not self.process or not self.process.stdout:
            return None
        line = await self.process.stdout.readline()
        if not line:
            return None
        try:
            data = json.loads(line.decode("utf-8").strip())
            if "method" in data:
                if "id" in data:
                    return JSONRPCRequest(id=data["id"], method=data["method"], params=data.get("params"))
                return JSONRPCNotification(method=data["method"], params=data.get("params"))
            return JSONRPCResponse.from_dict(data)
        except Exception as e:
            log.warning("Failed to parse JSON-RPC line from MCP server stdout: %s", e)
            return None

    async def close(self) -> None:
        self._connected = False
        if self.process:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=2.0)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            finally:
                self.process = None
