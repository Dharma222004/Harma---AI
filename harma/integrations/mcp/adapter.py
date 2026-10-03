"""
Harma MCP — Tool Adapter

Adapts an external MCP tool into Harma's native BaseTool abstraction so that
ToolRegistry, HarmaAgent, and Executor can reason about and execute it identically
to built-in tools.
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from harma.config.logging_config import get_logger
from harma.integrations.circuit_breaker import CircuitBreaker, RateLimiter
from harma.integrations.credentials import get_secret_redactor
from harma.integrations.exceptions import SchemaValidationError
from harma.integrations.mcp.client import MCPClient
from harma.integrations.models import IntegrationToolDef
from harma.tools.base import BaseTool, PermissionLevel, ToolResult

log = get_logger(__name__)


class MCPToolAdapter(BaseTool):
    """
    Wraps an external MCP tool as a native Harma BaseTool with schema validation,
    circuit breaker protection, rate limiting, and output secret redaction.
    """

    def __init__(
        self,
        tool_def: IntegrationToolDef,
        client: MCPClient,
        circuit_breaker: Optional[CircuitBreaker] = None,
        rate_limiter: Optional[RateLimiter] = None,
        timeout_seconds: float = 30.0,
        dry_run: bool = False,
    ) -> None:
        self.tool_def = tool_def
        self.client = client
        self.circuit_breaker = circuit_breaker
        self.rate_limiter = rate_limiter
        self.timeout_seconds = timeout_seconds
        self.dry_run = dry_run

        # BaseTool required attributes
        self.name = tool_def.name
        self.description = tool_def.description
        self.permission_level = tool_def.permission_level
        self.parameters = tool_def.input_schema or {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Validate input schema and execute tool on remote MCP server."""
        start_time = time.time()

        # 1. Dry Run simulation for non-safe actions
        if self.dry_run and self.permission_level != PermissionLevel.SAFE:
            log.info("DRY_RUN simulating MCP tool %s with args %s", self.name, kwargs)
            return ToolResult(
                success=True,
                output=f"[DRY RUN] Would execute external tool '{self.name}' on server '{self.tool_def.server_name}' with arguments: {kwargs}",
                data={"dry_run": True, "server": self.tool_def.server_name, "tool": self.name, "arguments": kwargs},
            )

        # 2. Schema validation
        validation_errors = self._validate_schema(kwargs)
        if validation_errors:
            err_msg = f"Schema validation failed for tool '{self.name}': {'; '.join(validation_errors)}"
            log.warning(err_msg)
            raise SchemaValidationError(err_msg, tool_name=self.name, errors=validation_errors)

        # 3. Circuit breaker check
        if self.circuit_breaker:
            self.circuit_breaker.check_state()

        # 4. Rate limiter check / pace
        if self.rate_limiter:
            await self.rate_limiter.acquire()

        # 5. Remote execution
        try:
            raw_result = await self.client.call_tool(self.tool_def.original_name, kwargs)
            duration_ms = (time.time() - start_time) * 1000.0

            if self.circuit_breaker:
                self.circuit_breaker.record_success()

            # Format and redact output
            is_error = raw_result.get("isError", False)
            content_list = raw_result.get("content", [])
            text_parts = []
            for item in content_list:
                if isinstance(item, dict) and "text" in item:
                    text_parts.append(str(item["text"]))
                else:
                    text_parts.append(str(item))

            output_text = "\n".join(text_parts) if text_parts else str(raw_result.get("data", ""))
            redacted_output = get_secret_redactor().redact_text(output_text)
            redacted_data = get_secret_redactor().redact_payload(raw_result.get("data"))

            return ToolResult(
                success=not is_error,
                output=redacted_output,
                data=redacted_data,
                error=redacted_output if is_error else None,
            )

        except Exception as e:
            if self.circuit_breaker:
                self.circuit_breaker.record_failure(e)
            log.error("Execution failed for MCP tool '%s': %s", self.name, e)
            redacted_error = get_secret_redactor().redact_text(str(e))
            return ToolResult(
                success=False,
                output="",
                error=f"MCP tool '{self.name}' error: {redacted_error}",
            )

    def _validate_schema(self, args: dict[str, Any]) -> list[str]:
        """Validate input arguments against advertised JSON schema."""
        errors: list[str] = []
        if not self.parameters or not isinstance(self.parameters, dict):
            return errors

        # Check required fields
        required = self.parameters.get("required", [])
        for req in required:
            if req not in args or args[req] is None:
                errors.append(f"Missing required parameter '{req}'")

        # Basic type checking if properties declared
        props = self.parameters.get("properties", {})
        for key, val in args.items():
            if key in props and val is not None:
                expected_type = props[key].get("type")
                if expected_type == "string" and not isinstance(val, str):
                    errors.append(f"Parameter '{key}' must be a string, got {type(val).__name__}")
                elif expected_type == "integer" and not isinstance(val, int):
                    errors.append(f"Parameter '{key}' must be an integer, got {type(val).__name__}")
                elif expected_type == "boolean" and not isinstance(val, bool):
                    errors.append(f"Parameter '{key}' must be a boolean, got {type(val).__name__}")
                elif expected_type == "array" and not isinstance(val, list):
                    errors.append(f"Parameter '{key}' must be an array, got {type(val).__name__}")
                elif expected_type == "object" and not isinstance(val, dict):
                    errors.append(f"Parameter '{key}' must be an object, got {type(val).__name__}")

        return errors
