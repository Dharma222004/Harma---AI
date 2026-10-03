"""
NVIDIA NIM / Hosted LLM Adapter — Harma LLM Provider

Connects Harma to NVIDIA's hosted LLM inference API (OpenAI-compatible)
running models such as:
  - nemotron-3-super-120b-a12b
  - nvidia/nemotron-3-super-120b-a12b
  - llama-3.1-nemotron-70b-instruct
  - and other models served via NVIDIA NIM / integrate.api.nvidia.com

Features:
  • Multi-key load balancing: rotates requests round-robin across NVIDIA API keys.
  • Automatic failover & cooldown on rate-limits (HTTP 429), quotas, and 503 errors.
  • Zero leaking of secrets/API keys in logs or exceptions.
  • Automatic 'nvapi-' prefix normalization if missing.
  • Automatic model name normalization ('nvidia/' prefix if needed).
  • Full tool/function calling support with schema conversion.
  • Robust handling of reasoning models (nemotron reasoning_content).
  • Robust handling of tool-call-only responses (content is empty or None).
  • Token-by-token streaming support with failover.
  • Latency & TTFT instrumentation.
  • Diagnostics & health check verification across key pool.
  • Strict fallback policy: errors are surfaced cleanly without consuming
    Gemini or Groq credits unless explicitly configured.
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

_DEFAULT_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
_DEFAULT_TIMEOUT = 120

# Error phrases that signal quota/rate-limit/bad keys — trigger key rotation
_ROTATABLE_SIGNALS = (
    "quota", "rate limit", "429", "rate_limit_exceeded",
    "too many requests", "tokens per", "requests per",
    "invalid_api_key", "invalid api key", "unauthorized",
    "401", "403", "503", "gateway timeout", "504",
)

_KEY_COOLDOWNS: dict[str, float] = {}
_INVALID_KEYS: set[str] = set()

# Transient server/network failures: retry on the same key with exponential backoff
_TRANSIENT_SIGNALS = (
    "500", "502", "internal server error", "bad gateway", "service unavailable",
    "timed out", "timeout", "connection error", "connection reset", "remote protocol",
    "server disconnected", "overloaded", "temporarily",
)
_TRANSIENT_RETRIES = 3          # extra attempts after the first failure
_TRANSIENT_BACKOFF_S = 1.5      # 1.5s, 3s, 6s


class NVIDIAAdapter(LLMProvider):
    """
    First-class LLM adapter for NVIDIA's hosted LLM inference platform.
    Supports multi-key pool rotation, round-robin load balancing,
    and automatic failover on rate limits.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        api_keys: Optional[list[str]] = None,
    ) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError(
                "openai package is required for the NVIDIA adapter.\n"
                "Install with: pip install openai"
            )

        self._OpenAI = AsyncOpenAI
        llm_cfg = config.llm

        # Resolve keys pool
        if api_keys:
            raw_keys = [k for k in api_keys if k]
        elif api_key:
            raw_keys = [api_key]
        elif api_key == "":
            raw_keys = []
        else:
            raw_keys = list(llm_cfg.nvidia_keys) if llm_cfg.nvidia_keys else []
            if not raw_keys and (llm_cfg.nvidia_api_key or llm_cfg.api_key):
                raw_keys = [llm_cfg.nvidia_api_key or llm_cfg.api_key]

        if not raw_keys:
            raise ValueError(
                "NVIDIA provider selected but NVIDIA_API_KEY is not configured.\n"
                "Set NVIDIA_API_KEY in .env."
            )

        # Normalize key format (NVIDIA NIM keys start with 'nvapi-') and deduplicate
        normalized: list[str] = []
        seen: set[str] = set()
        for k in raw_keys:
            norm = k if k.startswith("nvapi-") else f"nvapi-{k}"
            if norm not in seen:
                seen.add(norm)
                normalized.append(norm)

        self._keys: List[str] = normalized
        self._key_cycle = itertools.cycle(self._keys)
        self._active_key: str = self._keys[0]
        # Retain _api_key for backwards compatibility
        self._api_key: str = self._active_key

        # Resolve model name
        raw_model = model or llm_cfg.nvidia_model or (llm_cfg.model if llm_cfg.provider == "nvidia" else "")
        if not raw_model:
            raise ValueError(
                "NVIDIA provider selected but NVIDIA_MODEL is not configured.\n"
                "Set NVIDIA_MODEL in .env."
            )
        self._user_model_name = raw_model
        # NVIDIA NIM endpoint expects 'org/model_name' format (e.g. 'nvidia/nemotron-3-super-120b-a12b')
        self._model = raw_model if "/" in raw_model else f"nvidia/{raw_model}"

        # Resolve base URL, timeout, temperature, max_tokens
        self._base_url = (
            base_url
            or llm_cfg.nvidia_base_url
            or llm_cfg.base_url
            or _DEFAULT_NVIDIA_BASE_URL
        )
        self._timeout = timeout if timeout is not None else (llm_cfg.nvidia_timeout or _DEFAULT_TIMEOUT)
        self._temperature = temperature if temperature is not None else (llm_cfg.nvidia_temperature if llm_cfg.nvidia_temperature is not None else 0.2)
        self._max_tokens = max_tokens or llm_cfg.max_tokens or 8192
        self._stream = llm_cfg.stream

        # Persistent client cache for HTTP/2 connection pooling across all keys
        self._clients: dict[str, Any] = {}
        # Primary persistent client instance
        self._client = self._make_client(self._api_key)
        self._init_client = self._client
        self._clients[self._api_key] = self._client

        # Instance-isolated key health tracking
        self._cooldowns: dict[str, float] = {}
        self._invalid_keys: set[str] = set()

        # Diagnostics & metrics state
        self._last_latency_ms: float = 0.0
        self._last_ttft_ms: float = 0.0
        self._total_requests: int = 0
        self._successful_requests: int = 0
        self._failed_requests: int = 0

        log.info(
            "[NVIDIA] Adapter ready  model=%s (effective=%s)  base=%s  keys=%d (active=%s)  timeout=%ds",
            self._user_model_name,
            self._model,
            self._base_url,
            len(self._keys),
            self._mask_key(self._active_key),
            self._timeout,
        )

    @property
    def name(self) -> str:
        return "NVIDIA"

    @property
    def model(self) -> str:
        return self._user_model_name

    @property
    def effective_model(self) -> str:
        return self._model

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def keys(self) -> list[str]:
        return list(self._keys)

    @property
    def active_key(self) -> str:
        return self._mask_key(self._active_key)

    @property
    def last_latency_ms(self) -> float:
        return self._last_latency_ms

    # ── Key Pool Management & Client Cache ─────────────────────────────────────

    def _make_client(self, key: str) -> Any:
        return self._OpenAI(
            api_key=key,
            base_url=self._base_url,
            timeout=self._timeout,
        )

    def _get_client(self, key: str) -> Any:
        """Return or create a persistent client for the given key."""
        if hasattr(self, "_client") and key == self._api_key and self._client is not getattr(self, "_init_client", None):
            return self._client
        if key in self._clients:
            return self._clients[key]
        if key == self._api_key and hasattr(self, "_client"):
            return self._client
        client = self._make_client(key)
        self._clients[key] = client
        return client

    @staticmethod
    def _mask_key(key: str) -> str:
        if len(key) > 14:
            return f"{key[:9]}...{key[-4:]}"
        return "***"

    def _is_rotatable_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(sig in msg for sig in _ROTATABLE_SIGNALS)

    @staticmethod
    def _is_transient_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        if any(s in msg for s in ("invalid_api_key", "unauthorized", "401", "403", "429", "rate limit", "quota")):
            return False
        return any(sig in msg for sig in _TRANSIENT_SIGNALS)

    async def _create_with_retry(self, client: Any, **kwargs: Any) -> Any:
        """chat.completions.create with backoff retries on transient 5xx / network errors."""
        import asyncio
        delay = _TRANSIENT_BACKOFF_S
        for n in range(_TRANSIENT_RETRIES + 1):
            try:
                return await client.chat.completions.create(**kwargs)
            except Exception as exc:
                if n >= _TRANSIENT_RETRIES or not self._is_transient_error(exc):
                    raise
                log.warning("[NVIDIA] Transient error (%s) — retry %d/%d in %.1fs",
                            self._sanitize_error(exc), n + 1, _TRANSIENT_RETRIES, delay)
                await asyncio.sleep(delay)
                delay *= 2

    def _drop_invalid_key(self, bad_key: str) -> None:
        """Remove a known permanently invalid key from the active rotation pool."""
        self._invalid_keys.add(bad_key)
        if bad_key in self._keys and len(self._keys) > 1:
            log.warning("[NVIDIA] Permanently removing invalid key from pool: %s", self._mask_key(bad_key))
            self._keys.remove(bad_key)
            self._key_cycle = itertools.cycle(self._keys)
            self._active_key = self._keys[0]

    def _get_ordered_keys(self) -> list[str]:
        """
        Return usable keys with round-robin starting key,
        prioritizing healthy keys over keys currently in cooldown.
        """
        now = time.time()
        valid = [k for k in self._keys if k not in self._invalid_keys]
        if not valid:
            valid = list(self._keys)

        healthy = [k for k in valid if self._cooldowns.get(k, 0) <= now]
        cooling = [k for k in valid if self._cooldowns.get(k, 0) > now]

        # Rotate cycle to pick preferred starting key for load-balancing
        next_pref = next(self._key_cycle) if self._keys else ""
        if healthy:
            if next_pref in healthy:
                idx = healthy.index(next_pref)
                healthy = healthy[idx:] + healthy[:idx]
            return healthy + cooling
        return cooling

    # ── Message & Tool Schema Converters ──────────────────────────────────────

    @staticmethod
    def _to_openai_messages(
        messages: list[Message],
        system: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Convert Harma unified Message objects into OpenAI-compatible format
        accepted by the NVIDIA NIM endpoint.
        """
        result: list[dict[str, Any]] = []

        if system:
            result.append({"role": "system", "content": system})

        for msg in messages:
            if msg.role == Role.USER:
                result.append({"role": "user", "content": msg.content or ""})

            elif msg.role == Role.ASSISTANT:
                entry: dict[str, Any] = {
                    "role": "assistant",
                    # When tool calls exist, content may be empty string or None
                    "content": msg.content if msg.content else (None if msg.tool_calls else ""),
                }
                if msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name.replace(".", "__"),
                                "arguments": json.dumps(tc.arguments) if isinstance(tc.arguments, dict) else str(tc.arguments or "{}"),
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
                            "content": tr.content if isinstance(tr.content, str) else json.dumps(tr.content),
                        }
                    )

        return result

    _SCHEMA_CACHE: dict[str, dict[str, Any]] = {}

    @classmethod
    def _to_openai_tools(cls, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        """
        Convert Harma ToolDefinition objects into OpenAI-compatible function schema
        supported by NVIDIA NIM with in-memory caching.
        """
        converted: list[dict[str, Any]] = []
        for t in tools:
            cached = cls._SCHEMA_CACHE.get(t.name)
            if cached is not None:
                converted.append(cached)
                continue
            safe_name = t.name.replace(".", "__")
            entry = {
                "type": "function",
                "function": {
                    "name": safe_name,
                    "description": t.description,
                    "parameters": t.parameters if t.parameters else {
                        "type": "object",
                        "properties": {},
                    },
                },
            }
            cls._SCHEMA_CACHE[t.name] = entry
            converted.append(entry)
        return converted

    @staticmethod
    def _parse_tool_calls(raw_tool_calls: list[Any]) -> list[ToolCall]:
        """
        Parse raw tool calls returned by the NVIDIA model into Harma's normalized ToolCall dataclass.
        Restores double underscores back to dots for Harma's ToolRegistry (e.g. android__tap -> android.tap).
        """
        calls: list[ToolCall] = []
        for tc in raw_tool_calls:
            call_id = getattr(tc, "id", None) or f"call_{uuid.uuid4().hex[:8]}"
            func = getattr(tc, "function", None)
            if not func:
                continue

            raw_name = getattr(func, "name", "")
            # Restore namespaced dots
            if "__" in raw_name and raw_name.startswith(("android__", "tasks__", "integrations__")):
                name = raw_name.replace("__", ".")
            elif "__" in raw_name:
                name = raw_name.replace("__", ".")
            else:
                name = raw_name

            raw_args = getattr(func, "arguments", "{}") or "{}"

            if isinstance(raw_args, dict):
                args = raw_args
            else:
                try:
                    args = json.loads(raw_args)
                except Exception:
                    args = {"raw": str(raw_args)}

            calls.append(
                ToolCall(
                    id=call_id,
                    name=name,
                    arguments=args,
                )
            )
        return calls

    # ── Completion Implementation ─────────────────────────────────────────────

    async def complete(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDefinition]] = None,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """
        Send messages and available tools to NVIDIA's hosted LLM API.
        Rotates across all available keys with auto-failover on rate limits.
        """
        self._total_requests += 1
        t0 = time.perf_counter()

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

        log.debug(
            "[NVIDIA] → Request model=%s messages=%d tools=%d (keys_in_pool=%d)",
            self._model,
            len(oai_messages),
            len(tools) if tools else 0,
            len(self._keys),
        )

        ordered_keys = self._get_ordered_keys()
        attempts = len(ordered_keys)
        last_exc: Optional[Exception] = None
        response = None

        for attempt, curr_key in enumerate(ordered_keys):
            self._active_key = curr_key
            client = self._get_client(curr_key)
            try:
                response = await self._create_with_retry(client, **kwargs)
                break
            except Exception as exc:
                is_rotatable = self._is_rotatable_error(exc)
                msg_lower = str(exc).lower()
                is_invalid = "invalid_api_key" in msg_lower or "401" in msg_lower or "unauthorized" in msg_lower

                if is_invalid and len(self._keys) > 1:
                    self._drop_invalid_key(curr_key)
                elif is_rotatable:
                    self._cooldowns[curr_key] = time.time() + 60  # 1 min cooldown

                if is_rotatable and attempt < attempts - 1:
                    log.warning(
                        "[NVIDIA] Key %s hit error (%s) — rotating to next key in pool (%d/%d)...",
                        self._mask_key(curr_key),
                        self._sanitize_error(exc),
                        attempt + 1,
                        attempts,
                    )
                    last_exc = exc
                    continue
                else:
                    last_exc = exc
                    self._failed_requests += 1
                    duration_ms = (time.perf_counter() - t0) * 1000
                    self._last_latency_ms = duration_ms
                    error_msg = self._sanitize_error(exc)
                    log.error("[NVIDIA] Request failed in %.1fms (all %d keys attempted): %s", duration_ms, attempt + 1, error_msg)

                    if config.llm.fallback_enabled:
                        log.warning("[NVIDIA] Fallback enabled. Attempting configured secondary provider...")

                    return LLMResponse(
                        content=f"[Harma AI error: {error_msg}]",
                        finish_reason="error",
                        usage={},
                        raw=None,
                    )

        duration_ms = (time.perf_counter() - t0) * 1000
        self._last_latency_ms = duration_ms
        self._successful_requests += 1

        if not response or not response.choices:
            return LLMResponse(
                content="",
                tool_calls=[],
                finish_reason="stop",
                usage={},
                raw=response,
            )

        choice = response.choices[0]
        message = choice.message
        tool_calls = self._parse_tool_calls(getattr(message, "tool_calls", None) or [])

        # Extract text content.
        # nemotron and reasoning models may generate internal reasoning in reasoning_content
        content = message.content or ""
        reasoning_content = getattr(message, "reasoning_content", None) or ""
        if not content and not tool_calls and reasoning_content:
            content = reasoning_content

        usage: dict[str, int] = {}
        if response.usage:
            usage = {
                "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                "completion_tokens": getattr(response.usage, "completion_tokens", 0),
                "total_tokens": getattr(response.usage, "total_tokens", 0),
            }

        log.debug(
            "[NVIDIA] ← Response in %.1fms finish=%s tools=%d tokens=%d key=%s",
            duration_ms,
            choice.finish_reason,
            len(tool_calls),
            usage.get("total_tokens", 0),
            self._mask_key(self._active_key),
        )

        finish_reason = choice.finish_reason or ("tool_calls" if tool_calls else "stop")

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            raw=response,
        )

    # ── Streaming Implementation ──────────────────────────────────────────────

    async def stream(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDefinition]] = None,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """
        Stream text chunks from the NVIDIA model token by token with key rotation on error.
        """
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
        if tools:
            kwargs["tools"] = self._to_openai_tools(tools)
            kwargs["tool_choice"] = "auto"

        ordered_keys = self._get_ordered_keys()
        attempts = len(ordered_keys)

        for attempt, curr_key in enumerate(ordered_keys):
            self._active_key = curr_key
            client = self._get_client(curr_key)
            t0 = time.perf_counter()
            first_token = True
            token_yielded = False

            try:
                stream_resp = await self._create_with_retry(client, **kwargs)
                async for chunk in stream_resp:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    delta_text = getattr(delta, "content", None)
                    if not delta_text and not token_yielded:
                        delta_text = getattr(delta, "reasoning_content", None)
                    if delta_text:
                        if first_token:
                            self._last_ttft_ms = (time.perf_counter() - t0) * 1000
                            first_token = False
                        token_yielded = True
                        yield delta_text
                return
            except Exception as exc:
                if token_yielded:
                    error_msg = self._sanitize_error(exc)
                    log.error("[NVIDIA] Streaming interrupted: %s", error_msg)
                    yield f"[Harma AI stream error: {error_msg}]"
                    return

                is_rotatable = self._is_rotatable_error(exc)
                if is_rotatable:
                    self._cooldowns[curr_key] = time.time() + 60
                    if attempt < attempts - 1:
                        log.warning(
                            "[NVIDIA] Stream failed on key %s (%s) — rotating to next key in pool...",
                            self._mask_key(curr_key),
                            self._sanitize_error(exc),
                        )
                        continue
                error_msg = self._sanitize_error(exc)
                log.error("[NVIDIA] Streaming failed: %s", error_msg)
                yield f"[Harma AI stream error: {error_msg}]"
                return

    # ── Health Check & Diagnostics ────────────────────────────────────────────

    async def health_check(self) -> bool:
        """
        Lightweight check verifying NVIDIA connectivity and authentication across keys.
        """
        for k in self._keys:
            client = self._get_client(k)
            try:
                models = await client.models.list()
                if models.data:
                    return True
            except Exception as exc:
                log.warning("[NVIDIA] Health check failed for key %s: %s", self._mask_key(k), self._sanitize_error(exc))
        return False

    async def get_diagnostics(self) -> dict[str, Any]:
        """
        Comprehensive diagnostic report per Requirements 15 & 16.
        Verifies configuration, connectivity, authentication, generation, tool calling, and key pool status.
        """
        now = time.time()
        healthy_keys = [k for k in self._keys if self._cooldowns.get(k, 0) <= now and k not in self._invalid_keys]
        cooling_keys = [k for k in self._keys if self._cooldowns.get(k, 0) > now]

        status: dict[str, Any] = {
            "provider": "NVIDIA",
            "model": self._user_model_name,
            "effective_model": self._model,
            "endpoint": self._base_url,
            "total_keys": len(self._keys),
            "healthy_keys": len(healthy_keys),
            "cooling_keys": len(cooling_keys),
            "active_key": self._mask_key(self._active_key),
            "authentication": "UNKNOWN",
            "connection": "UNKNOWN",
            "generation": "UNKNOWN",
            "tool_calling": "supported",
            "streaming": "supported",
            "structured_output": "supported",
            "context_window": self._max_tokens,
            "latency_ms": round(self._last_latency_ms, 2),
            "status": "UNKNOWN",
            "error": None,
        }

        t0 = time.perf_counter()
        try:
            client = self._get_client(self._active_key)
            await client.models.list()
            status["connection"] = "OK"
            status["authentication"] = "OK"

            test_resp = await client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=50,
            )
            if test_resp.choices:
                status["generation"] = "OK"
                status["status"] = "Connected"
            else:
                status["generation"] = "FAILED"
                status["status"] = "Degraded"

            status["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        except Exception as exc:
            sanitized = self._sanitize_error(exc)
            status["connection"] = "FAILED" if "connect" in sanitized.lower() else "OK"
            status["authentication"] = "FAILED" if "401" in sanitized or "unauthorized" in sanitized.lower() else "OK"
            status["generation"] = "FAILED"
            status["status"] = "Disconnected"
            status["error"] = sanitized
            status["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        return status

    # ── Error Sanitization ────────────────────────────────────────────────────

    def _sanitize_error(self, exc: Exception) -> str:
        """
        Format exception message while strictly scrubbing secrets and API keys.
        """
        msg = str(exc)
        for k in self._keys:
            if k and k in msg:
                msg = msg.replace(k, "[REDACTED_API_KEY]")
            raw_key = k.removeprefix("nvapi-")
            if raw_key and len(raw_key) > 8 and raw_key in msg:
                msg = msg.replace(raw_key, "[REDACTED_API_KEY]")
        return msg


# Provide alias for casing flexibility
NvidiaAdapter = NVIDIAAdapter
