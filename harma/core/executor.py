"""
Harma Executor

Responsible for a single step in the agent loop:
  1. Check permissions for each tool call requested by the LLM.
  2. Get user confirmation when required.
  3. Execute approved tool calls.
  4. Return collected ToolResults back to the loop.

The executor is intentionally stateless — it receives everything it needs
from the agent loop and returns results. State lives in ShortTermMemory.
"""

from __future__ import annotations

import json
from typing import Callable, Optional

from harma.config.logging_config import get_logger
from harma.core.context import AgentContext
from harma.llm.provider import ToolCall, ToolResult
from harma.security.permissions import PermissionDecision
from harma.tools.base import PermissionLevel

log = get_logger(__name__)

# Signature: (prompt: str) -> str
ConfirmCallback = Callable[[str], str]


class Executor:
    """
    Executes tool calls under permission control.

    Args:
        context: The shared AgentContext.
        confirm_callback: Function called when user confirmation is required.
                          Receives the prompt string, returns user's response string.
                          Defaults to a CLI stdin prompt.
    """

    def __init__(
        self,
        context: AgentContext,
        confirm_callback: Optional[ConfirmCallback] = None,
    ) -> None:
        self._ctx = context
        self._confirm = confirm_callback or self._cli_confirm

    @staticmethod
    def _cli_confirm(prompt: str) -> str:
        """Default confirmation: ask via stdin."""
        print(f"\n{prompt}")
        return input("> ").strip()

    async def run_tool_calls(
        self, tool_calls: list[ToolCall]
    ) -> list[ToolResult]:
        """
        Execute a list of tool calls requested by the LLM.

        For each call:
          - Look up the tool in the registry.
          - Check permissions.
          - Optionally get user confirmation.
          - Execute and collect result.

        Args:
            tool_calls: Tool calls from the LLM response.

        Returns:
            List of ToolResult objects, one per tool call.
        """
        results: list[ToolResult] = []

        for tc in tool_calls:
            result = await self._execute_one(tc)
            results.append(result)

        return results

    async def _execute_one(self, tc: ToolCall) -> ToolResult:
        """Execute a single tool call under permission control."""
        tool = self._ctx.registry.get(tc.name)

        if not tool:
            log.warning("Unknown tool requested: %s", tc.name)
            return ToolResult(
                tool_call_id=tc.id,
                name=tc.name,
                content=json.dumps({
                    "error": f"Tool '{tc.name}' is not available.",
                    "available": [t.name for t in self._ctx.registry.list_tools()],
                }),
                is_error=True,
            )

        # ── Permission check ──────────────────────────────────────────────────
        decision = self._ctx.permissions.check(
            tool_name=tc.name,
            permission_level=tool.permission_level,
        )

        if decision == PermissionDecision.DENIED:
            log.warning("Tool '%s' denied by permission policy.", tc.name)
            return ToolResult(
                tool_call_id=tc.id,
                name=tc.name,
                content=json.dumps({"error": f"Action '{tc.name}' was denied by permission policy."}),
                is_error=True,
            )

        if decision == PermissionDecision.NEEDS_CONFIRMATION:
            prompt = self._ctx.permissions.build_confirmation_prompt(
                tool_name=tc.name,
                permission_level=tool.permission_level,
                arguments=tc.arguments,
            )
            answer = self._confirm(prompt)
            if answer.lower() not in ("y", "yes"):
                log.info("Tool '%s' rejected by user.", tc.name)
                return ToolResult(
                    tool_call_id=tc.id,
                    name=tc.name,
                    content=json.dumps({"error": "Action was cancelled by the user."}),
                    is_error=True,
                )

        # ── Execute ────────────────────────────────────────────────────────────
        bus = None
        try:
            from harma.api.events import get_event_bus
            bus = get_event_bus()
            bus.publish(
                "tool.started",
                source="executor",
                payload={"tool": tc.name, "arguments": tc.arguments},
            )
        except Exception:
            bus = None

        tool_result = await self._ctx.registry.call(tc.name, **tc.arguments)

        if bus:
            try:
                bus.publish(
                    "tool.completed",
                    source="executor",
                    payload={
                        "tool": tc.name,
                        "success": tool_result.success,
                        "output": str(tool_result.output)[:120],
                    },
                )
            except Exception:
                pass

        return ToolResult(
            tool_call_id=tc.id,
            name=tc.name,
            content=tool_result.output if tool_result.success else json.dumps({"error": tool_result.error}),
            is_error=not tool_result.success,
        )
