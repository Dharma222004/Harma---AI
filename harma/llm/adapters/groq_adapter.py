"""
Groq LLM Adapter — Phase 1 Extension

Groq is an OpenAI-compatible inference API running models like:
  - openai/gpt-oss-120b
  - llama-3.3-70b-versatile
  - mixtral-8x7b-32768
  - llama-3.1-8b-instant

This adapter reuses the OpenAI client pointed at Groq's base URL,
and supports automatic key rotation across all GROQ_API_KEY_1..4.
"""

from __future__ import annotations

import itertools
import json
import time
import uuid
from typing import Any, AsyncIterator, List, Optional

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

# Error phrases that signal quota/rate-limit/bad keys — trigger key rotation
_ROTATABLE_SIGNALS = (
    "quota", "rate limit", "429", "rate_limit_exceeded",
    "too many requests", "tokens per", "requests per",
    "invalid_api_key", "invalid api key", "unauthorized", "401", "403", "503",
)

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_KEY_COOLDOWNS: dict[str, float] = {}
_INVALID_KEYS: set[str] = set()


class GroqAdapter(LLMProvider):
    """
    Adapter for Groq Inference API using OpenAI-compatible client.

    Key rotation:
        All GROQ_API_KEY_1..4 keys are tried in round-robin order.
        On rate-limit / invalid-key errors, healthy keys are prioritized
        and rotated automatically.
    """

    def __init__(self, api_keys: Optional[list[str]] = None) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError(
                "openai package is required for the Groq adapter.\n"
                "Install with:  pip install openai"
            )

        llm_cfg = config.llm
        keys = api_keys if api_keys else llm_cfg.groq_keys
        if not keys:
            raise ValueError(
                "No Groq API keys found. "
                "Set GROQ_API_KEY_1 (and optionally 2-4) in your .env file."
            )

        self._OpenAI = AsyncOpenAI
        self._keys: List[str] = list(keys)
        self._key_cycle = itertools.cycle(self._keys)
        self._active_key: str = next(self._key_cycle)
        self._base_url = llm_cfg.groq_base_url or _GROQ_BASE_URL
        self._model = llm_cfg.groq_model or "openai/gpt-oss-120b"
        self._temperature = llm_cfg.temperature
        self._max_tokens = llm_cfg.max_tokens
        self._timeout = llm_cfg.timeout

        log.info(
            "[GROQ] Adapter ready  model=%s  base=%s  keys=%d",
            self._model, self._base_url, len(self._keys),
        )

    @property
    def name(self) -> str:
        return "Groq"

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _make_client(self, api_key: str):
        return self._OpenAI(
            api_key=api_key,
            base_url=self._base_url,
            timeout=self._timeout,
        )

    def _next_key(self) -> str:
        self._active_key = next(self._key_cycle)
        return self._active_key

    def _is_rotatable_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(sig in msg for sig in _ROTATABLE_SIGNALS)

    def _drop_invalid_key(self, bad_key: str) -> None:
        """Remove a known permanently invalid key from the active rotation pool."""
        _INVALID_KEYS.add(bad_key)
        if bad_key in self._keys and len(self._keys) > 1:
            log.warning("[GROQ] Permanently removing invalid key from pool: %s...", bad_key[:8])
            self._keys.remove(bad_key)
            self._key_cycle = itertools.cycle(self._keys)
            self._active_key = next(self._key_cycle)

    def _get_ordered_keys(self) -> list[str]:
        """Return usable keys with healthy keys prioritized over keys currently in cooldown."""
        now = time.time()
        valid = [k for k in self._keys if k not in _INVALID_KEYS]
        if not valid:
            valid = list(self._keys)
        healthy = [k for k in valid if _KEY_COOLDOWNS.get(k, 0) <= now]
        cooling = [k for k in valid if _KEY_COOLDOWNS.get(k, 0) > now]
        return healthy if healthy else cooling

    @staticmethod
    def _to_messages(messages: list[Message], system: Optional[str]) -> list[dict]:
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
                    result.append({
                        "role": "tool",
                        "tool_call_id": tr.tool_call_id,
                        "content": tr.content,
                    })
        return result

    @staticmethod
    def _to_tools(tools: list[ToolDefinition]) -> list[dict]:
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
    def _parse_tool_calls(raw: list) -> list[ToolCall]:
        calls = []
        for tc in raw:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"raw": tc.function.arguments}
            calls.append(ToolCall(
                id=tc.id or str(uuid.uuid4()),
                name=tc.function.name,
                arguments=args,
            ))
        return calls

    # ── Core API ──────────────────────────────────────────────────────────────

    async def complete(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDefinition]] = None,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        ordered_keys = self._get_ordered_keys()
        attempts = len(ordered_keys)
        last_exc: Optional[Exception] = None

        for attempt, curr_key in enumerate(ordered_keys):
            client = self._make_client(curr_key)
            self._active_key = curr_key
            try:
                return await self._do_complete(client, messages, tools, system, temperature, max_tokens)
            except Exception as exc:
                is_rotatable = self._is_rotatable_error(exc)
                msg_lower = str(exc).lower()
                is_invalid = "invalid_api_key" in msg_lower or "invalid api key" in msg_lower

                if is_invalid:
                    _INVALID_KEYS.add(curr_key)
                    self._drop_invalid_key(curr_key)
                elif is_rotatable:
                    _KEY_COOLDOWNS[curr_key] = time.time() + 60  # 1 min cooldown

                if is_rotatable and attempt < attempts - 1:
                    log.warning(
                        "[GROQ] Key hit rate-limit/error (%s) — rotating to next key.",
                        exc,
                    )
                    last_exc = exc
                else:
                    log.error("[GROQ] Request failed: %s", exc)
                    return LLMResponse(content=f"[Groq error: {exc}]", finish_reason="error")

        log.error("[GROQ] All %d keys exhausted. Last error: %s", attempts, last_exc)
        return LLMResponse(content=f"[Groq error: all keys exhausted]", finish_reason="error")

    async def _do_complete(
        self,
        client,
        messages: list[Message],
        tools: Optional[list[ToolDefinition]],
        system: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> LLMResponse:
        oai_messages = self._to_messages(messages, system)
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": oai_messages,
            "temperature": temperature if temperature is not None else self._temperature,
            "max_tokens": max_tokens or self._max_tokens,
        }
        if tools:
            kwargs["tools"] = self._to_tools(tools)
            kwargs["tool_choice"] = "auto"

        log.debug("→ GROQ request  model=%s  messages=%d", self._model, len(oai_messages))
        response = await client.chat.completions.create(**kwargs)

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
            "← GROQ response  finish=%s  tools=%d  tokens=%d",
            choice.finish_reason, len(tool_calls), usage.get("total_tokens", 0),
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
        response = await self.complete(messages, tools, system, temperature, max_tokens)
        if response.content:
            yield response.content

    async def health_check(self) -> bool:
        try:
            client = self._make_client(self._active_key)
            models = await client.models.list()
            return True
        except Exception as exc:
            log.warning("[GROQ] Health check failed: %s", exc)
            return False
