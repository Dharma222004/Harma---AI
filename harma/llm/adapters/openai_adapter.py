"""
OpenAI / OpenAI-Compatible LLM Adapter

Supports:
  - OpenAI (GPT-4o, GPT-4, etc.)
  - Any OpenAI-compatible endpoint (Groq, Together, LM Studio, Ollama, etc.)
  - Streaming
  - Tool / function calling
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


class OpenAIAdapter(LLMProvider):
    """Adapter for OpenAI and OpenAI-compatible APIs."""

    def __init__(self) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError(
                "openai package is required for the OpenAI adapter.\n"
                "Install with:  pip install openai"
            )

        llm_cfg = config.llm
        self._client = AsyncOpenAI(
            api_key=llm_cfg.api_key or "sk-placeholder",
            base_url=llm_cfg.base_url or None,
            timeout=llm_cfg.timeout,
        )
        self._model = llm_cfg.model
        self._temperature = llm_cfg.temperature
        self._max_tokens = llm_cfg.max_tokens
        self._stream = llm_cfg.stream

    @property
    def name(self) -> str:
        return "OpenAI"

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _to_openai_messages(
        messages: list[Message],
        system: Optional[str],
    ) -> list[dict]:
        """Convert Harma Message objects to OpenAI message dicts."""
        result: list[dict] = []

        if system:
            result.append({"role": "system", "content": system})

        for msg in messages:
            if msg.role == Role.USER:
                result.append({"role": "user", "content": msg.content})

            elif msg.role == Role.ASSISTANT:
                entry: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
                if msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                result.append(entry)

            elif msg.role == Role.TOOL:
                for tr in msg.tool_results:
                    result.append(
                        {
                            "role": "tool",
                            "tool_call_id": tr.tool_call_id,
                            "content": tr.content,
                        }
                    )

        return result

    @staticmethod
    def _to_openai_tools(tools: list[ToolDefinition]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    @staticmethod
    def _parse_tool_calls(raw_tool_calls: list) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for tc in raw_tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"raw": tc.function.arguments}
            calls.append(
                ToolCall(
                    id=tc.id or str(uuid.uuid4()),
                    name=tc.function.name,
                    arguments=args,
                )
            )
        return calls

    # ── Public interface ──────────────────────────────────────────────────────

    async def complete(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDefinition]] = None,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        oai_messages = self._to_openai_messages(messages, system)
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": oai_messages,
            "temperature": temperature if temperature is not None else self._temperature,
            "max_tokens": max_tokens or self._max_tokens,
        }
        if tools:
            kwargs["tools"] = self._to_openai_tools(tools)
            kwargs["tool_choice"] = "auto"

        log.debug("→ LLM request  model=%s  messages=%d", self._model, len(oai_messages))

        try:
            response = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            log.error("LLM request failed: %s", exc)
            return LLMResponse(
                content=f"[LLM error: {exc}]",
                finish_reason="error",
            )

        choice = response.choices[0]
        message = choice.message
        tool_calls = self._parse_tool_calls(message.tool_calls or [])

        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        log.debug(
            "← LLM response  finish=%s  tools=%d  tokens=%d",
            choice.finish_reason,
            len(tool_calls),
            usage.get("total_tokens", 0),
        )

        return LLMResponse(
            content=message.content or "",
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
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
        if not self._stream:
            async for chunk in super().stream(messages, tools, system, temperature, max_tokens):
                yield chunk
            return

        oai_messages = self._to_openai_messages(messages, system)
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": oai_messages,
            "temperature": temperature if temperature is not None else self._temperature,
            "max_tokens": max_tokens or self._max_tokens,
            "stream": True,
        }

        try:
            async with await self._client.chat.completions.create(**kwargs) as stream:
                async for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        yield delta.content
        except Exception as exc:
            log.error("LLM stream failed: %s", exc)
            yield f"[Stream error: {exc}]"

    async def health_check(self) -> bool:
        try:
            models = await self._client.models.list()
            return len(models.data) > 0
        except Exception as exc:
            log.warning("OpenAI health check failed: %s", exc)
            return False
