"""
Harma MCP — Mock & In-Memory MCP Server

Deterministic, controllable in-process server for automated testing, integration tests,
and representative service simulations (GitHub, Google Calendar, Gmail, custom tools).
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine, Optional, Union

from harma.config.logging_config import get_logger
from harma.integrations.mcp.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    MCP_PROTOCOL_VERSION,
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
)
from harma.integrations.mcp.transport import MCPTransport

log = get_logger(__name__)


class MockMCPServer:
    """
    Controllable MCP Server for test suites and offline mock integrations.
    Supports injecting failures, latency, and simulated external services.
    """

    def __init__(self, name: str = "mock-server", transport: Optional[MCPTransport] = None) -> None:
        self.name = name
        self.transport = transport
        self.tools: dict[str, dict[str, Any]] = {}
        self.tool_handlers: dict[str, Callable[[dict[str, Any]], Coroutine[Any, Any, Any]]] = {}
        self.resources: dict[str, dict[str, Any]] = {}
        self.prompts: dict[str, dict[str, Any]] = {}

        # Controllable fault simulation
        self.simulate_latency_seconds: float = 0.0
        self.simulate_auth_failure: bool = False
        self.simulate_rate_limit: bool = False
        self.simulate_error_message: Optional[str] = None

        self._running: bool = False
        self._loop_task: Optional[asyncio.Task] = None

        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register default mock tools (GitHub, Calendar, Gmail, generic items)."""
        # 1. mock.get_user
        self.register_tool(
            name="mock.get_user",
            description="Fetch mock user profile and settings",
            input_schema={
                "type": "object",
                "properties": {"user_id": {"type": "string"}},
                "required": ["user_id"],
            },
            handler=self._handle_get_user,
        )

        # 2. mock.list_items
        self.register_tool(
            name="mock.list_items",
            description="List inventory or stored items",
            input_schema={"type": "object", "properties": {"limit": {"type": "integer"}}},
            handler=self._handle_list_items,
        )

        # 3. mock.create_item
        self.register_tool(
            name="mock.create_item",
            description="Create a new stored item (write action)",
            input_schema={
                "type": "object",
                "properties": {"title": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}},
                "required": ["title"],
            },
            handler=self._handle_create_item,
        )

        # 4. mock.delete_item
        self.register_tool(
            name="mock.delete_item",
            description="Permanently delete an item (destructive action)",
            input_schema={"type": "object", "properties": {"item_id": {"type": "string"}}, "required": ["item_id"]},
            handler=self._handle_delete_item,
        )

        # 5. github.list_issues
        self.register_tool(
            name="github.list_issues",
            description="List open issues for a repository",
            input_schema={
                "type": "object",
                "properties": {"repo": {"type": "string"}},
                "required": ["repo"],
            },
            handler=self._handle_github_issues,
        )

        # 6. github.create_issue
        self.register_tool(
            name="github.create_issue",
            description="Create a new issue on GitHub",
            input_schema={
                "type": "object",
                "properties": {
                    "repo": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["repo", "title"],
            },
            handler=self._handle_github_create_issue,
        )

        # 7. calendar.list_events
        self.register_tool(
            name="calendar.list_events",
            description="List upcoming calendar events for today",
            input_schema={"type": "object", "properties": {"date": {"type": "string"}}},
            handler=self._handle_calendar_events,
        )

        # 8. gmail.list_messages
        self.register_tool(
            name="gmail.list_messages",
            description="List unread emails in inbox",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=self._handle_gmail_messages,
        )

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: Callable[[dict[str, Any]], Coroutine[Any, Any, Any]],
    ) -> None:
        self.tools[name] = {"name": name, "description": description, "inputSchema": input_schema}
        self.tool_handlers[name] = handler

    async def start(self) -> None:
        """Start listening for incoming client requests on transport."""
        if not self.transport:
            return
        if not self.transport.is_connected:
            await self.transport.connect()
        self._running = True
        self._loop_task = asyncio.create_task(self._serve_loop())

    async def stop(self) -> None:
        self._running = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
        if self.transport:
            await self.transport.close()

    async def _serve_loop(self) -> None:
        while self._running and self.transport and self.transport.is_connected:
            try:
                msg = await self.transport.receive()
                if msg is None:
                    break
                if isinstance(msg, JSONRPCRequest):
                    response = await self._handle_request(msg)
                    await self.transport.send(response)
                elif isinstance(msg, JSONRPCNotification):
                    # Notifications require no response
                    pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Error in MockMCPServer serve loop: %s", e)

    async def _handle_request(self, req: JSONRPCRequest) -> JSONRPCResponse:
        if self.simulate_latency_seconds > 0:
            await asyncio.sleep(self.simulate_latency_seconds)

        if self.simulate_auth_failure:
            return JSONRPCResponse(
                id=req.id,
                error=JSONRPCError(code=401, message="Unauthorized: authentication token expired or invalid"),
            )

        if self.simulate_rate_limit:
            return JSONRPCResponse(
                id=req.id,
                error=JSONRPCError(code=429, message="Rate limit exceeded: 429 Too Many Requests"),
            )

        if self.simulate_error_message:
            return JSONRPCResponse(
                id=req.id,
                error=JSONRPCError(code=INTERNAL_ERROR, message=self.simulate_error_message),
            )

        method = req.method
        params = req.params or {}

        if method == "initialize":
            return JSONRPCResponse(
                id=req.id,
                result={
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "serverInfo": {"name": self.name, "version": "1.0.0"},
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                        "prompts": {"listChanged": False},
                    },
                },
            )

        elif method == "ping":
            return JSONRPCResponse(id=req.id, result={})

        elif method == "tools/list":
            return JSONRPCResponse(id=req.id, result={"tools": list(self.tools.values())})

        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})
            if tool_name not in self.tool_handlers:
                return JSONRPCResponse(
                    id=req.id,
                    error=JSONRPCError(code=INVALID_PARAMS, message=f"Tool '{tool_name}' not found"),
                )
            try:
                data = await self.tool_handlers[tool_name](tool_args)
                return JSONRPCResponse(
                    id=req.id,
                    result={"content": [{"type": "text", "text": str(data)}], "isError": False, "data": data},
                )
            except Exception as e:
                return JSONRPCResponse(
                    id=req.id,
                    result={"content": [{"type": "text", "text": str(e)}], "isError": True},
                )

        elif method == "resources/list":
            return JSONRPCResponse(id=req.id, result={"resources": list(self.resources.values())})

        elif method == "prompts/list":
            return JSONRPCResponse(id=req.id, result={"prompts": list(self.prompts.values())})

        return JSONRPCResponse(
            id=req.id,
            error=JSONRPCError(code=METHOD_NOT_FOUND, message=f"Method '{method}' not implemented"),
        )

    # ── Default Tool Handlers ──────────────────────────────────────────────────

    async def _handle_get_user(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"user_id": args.get("user_id"), "name": "Harma User", "email": "user@harma.local", "role": "developer"}

    async def _handle_list_items(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        limit = args.get("limit", 10)
        items = [
            {"id": "item_1", "title": "Setup development environment"},
            {"id": "item_2", "title": "Run automated regression tests"},
            {"id": "item_3", "title": "Review deployment pipeline"},
        ]
        return items[:limit]

    async def _handle_create_item(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"id": "item_new_99", "title": args.get("title"), "created": True}

    async def _handle_delete_item(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"id": args.get("item_id"), "deleted": True}

    async def _handle_github_issues(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        repo = args.get("repo", "harma/core")
        return [
            {"number": 101, "title": "Add MCP integration support", "state": "open", "repo": repo},
            {"number": 102, "title": "Improve voice latency", "state": "open", "repo": repo},
        ]

    async def _handle_github_create_issue(self, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "number": 103,
            "title": args.get("title"),
            "body": args.get("body", ""),
            "state": "open",
            "url": f"https://github.com/{args.get('repo')}/issues/103",
        }

    async def _handle_calendar_events(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"id": "evt_1", "summary": "Harma Standup", "start": "09:00", "end": "09:30"},
            {"id": "evt_2", "summary": "Phase 8 Verification", "start": "14:00", "end": "15:00"},
        ]

    async def _handle_gmail_messages(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"id": "msg_1", "from": "ci@harma.local", "subject": "Test suite passed: 448/448"},
            {"id": "msg_2", "from": "notifications@github.com", "subject": "New issue assigned to you"},
        ]
