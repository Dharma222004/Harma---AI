"""
Anthropic Claude LLM Adapter

Supports:
  - Claude 3 Opus / Sonnet / Haiku
  - Tool use (function calling)
  - Streaming
"""

from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator, Optional

from harma.config.logging_config import get_logger
from harma.config.settings import config
from harma.llm.provider import (
    LLMProvider,
    LLMResponse,
    Message,
    Role,
    ToolCall,
    ToolDefinition,
)

log = get_logger(__name__)


class ClaudeAdapter(LLMProvider):
    """Adapter for Anthropic Claude via the anthropic SDK."""

    def __init__(self) -> None:
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "anthropic package is required for the Claude adapter.\n"
                "Install with:  pip install anthropic"
            )

        llm_cfg = config.llm
        self._client = anthropic.AsyncAnthropic(api_key=llm_cfg.api_key)
        self._model = llm_cfg.model or "claude-3-5-sonnet-20241022"
        self._temperature = llm_cfg.temperature
        self._max_tokens = llm_cfg.max_tokens

    @property
    def name(self) -> str:
        return "Claude"

    @staticmethod
    def _to_anthropic_messages(messages: list[Message]) -> list[dict]:
        result = []
        for msg in messages:
            if msg.role == Role.USER:
                result.append({"role": "user", "content": msg.content})
            elif msg.role == Role.ASSISTANT:
                content: list[dict] = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        }
                    )
                result.append({"role": "assistant", "content": content})
            elif msg.role == Role.TOOL:
                tool_result_content = []
                for tr in msg.tool_results:
                    tool_result_content.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tr.tool_call_id,
                            "content": tr.content,
                            "is_error": tr.is_error,
                        }
                    )
                result.append({"role": "user", "content": tool_result_content})
        return result

    @staticmethod
    def _to_anthropic_tools(tools: list[ToolDefinition]) -> list[dict]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in tools
        ]

    async def complete(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDefinition]] = None,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        import anthropic

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens or self._max_tokens,
            "temperature": temperature if temperature is not None else self._temperature,
            "messages": self._to_anthropic_messages(messages),
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self._to_anthropic_tools(tools)

        log.debug("→ Claude request  model=%s", self._model)

        try:
            response = await self._client.messages.create(**kwargs)
        except Exception as exc:
            log.error("Claude request failed: %s", exc)
            return LLMResponse(content=f"[Claude error: {exc}]", finish_reason="error")

        content = ""
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input or {},
                    )
                )

        finish = "tool_calls" if tool_calls else "stop"
        if response.stop_reason == "max_tokens":
            finish = "length"

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish,
            usage={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
            },
            raw=response,
        )

    async def stream(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDefinition]] = None,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        import anthropic

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens or self._max_tokens,
            "messages": self._to_anthropic_messages(messages),
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self._to_anthropic_tools(tools)

        try:
            async with self._client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception as exc:
            log.error("Claude stream failed: %s", exc)
            yield f"[Claude stream error: {exc}]"
