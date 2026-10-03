"""
Google Gemini LLM Adapter — Phase 1 (updated with key rotation)

Supports:
  - gemini-2.5-flash | gemini-2.5-pro | gemini-1.5-pro | gemini-1.5-flash
  - Tool / function calling
  - Streaming
  - Automatic API key rotation across up to 4 keys on quota errors
"""

from __future__ import annotations

import asyncio
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

# Error phrases that signal quota, rate-limit, or bad keys — trigger key rotation
_ROTATABLE_SIGNALS = (
    "quota", "rate limit", "429", "resource exhausted",
    "too many requests", "exceeded", "billing",
    "api_key_invalid", "api key not valid", "invalid api key",
    "unauthenticated", "permission_denied", "forbidden", "401", "403", "503",
)

_KEY_COOLDOWNS: dict[str, float] = {}
_INVALID_KEYS: set[str] = set()


class GeminiAdapter(LLMProvider):
    """
    Adapter for Google Gemini via the google-generativeai SDK.

    Key rotation:
        All GEMINI_API_KEY_1..4 keys are tried in round-robin order.
        On quota / rate-limit / invalid-key errors, the next key is tried automatically.
        If all keys are exhausted, the error is returned to the agent.
    """

    def __init__(self, api_keys: Optional[list[str]] = None) -> None:
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError(
                "google-generativeai package is required for the Gemini adapter.\n"
                "Install with:  pip install google-generativeai"
            )

        self._genai = genai
        llm_cfg = config.llm

        # Build key pool — deduplicated, non-empty
        if api_keys:
            all_keys = list(api_keys)
        else:
            all_keys = llm_cfg.api_keys if llm_cfg.api_keys else (
                [llm_cfg.api_key] if llm_cfg.api_key else []
            )
        if not all_keys:
            raise ValueError(
                "No Gemini API keys found. "
                "Set GEMINI_API_KEY_1 (and optionally 2-4) in your .env file."
            )
        self._keys: List[str] = list(all_keys)
        self._key_cycle = itertools.cycle(self._keys)
        self._active_key: str = next(self._key_cycle)

        self._model_name = llm_cfg.model or "gemini-2.5-flash"
        self._temperature = llm_cfg.temperature
        self._max_tokens = llm_cfg.max_tokens

        log.info(
            "[GEMINI] Adapter ready  model=%s  keys=%d",
            self._model_name, len(self._keys),
        )

    @property
    def name(self) -> str:
        return "Gemini"

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _configure_key(self, key: str) -> None:
        self._genai.configure(api_key=key)

    def _next_key(self) -> str:
        """Advance to the next key in rotation and configure it."""
        self._active_key = next(self._key_cycle)
        self._configure_key(self._active_key)
        return self._active_key

    def _is_rotatable_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(sig in msg for sig in _ROTATABLE_SIGNALS)

    def _drop_invalid_key(self, bad_key: str) -> None:
        """Remove a known permanently invalid key from the active rotation pool."""
        _INVALID_KEYS.add(bad_key)
        if bad_key in self._keys and len(self._keys) > 1:
            log.warning("[GEMINI] Permanently removing invalid key from pool: %s...", bad_key[:8])
            self._keys.remove(bad_key)
            self._key_cycle = itertools.cycle(self._keys)
            self._active_key = next(self._key_cycle)
            self._configure_key(self._active_key)

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
    def _sanitize_schema(schema: Any) -> Any:
        """
        Sanitize JSON schema for Google Generative AI Schema protobuf compatibility.
        Strips non-standard or unsupported fields like 'default', 'title', '$schema', etc.
        """
        if not isinstance(schema, dict):
            return schema

        allowed_keys = {
            "type", "format", "description", "nullable",
            "enum", "properties", "required", "items"
        }
        sanitized = {}
        for k, v in schema.items():
            if k in allowed_keys:
                if k == "properties" and isinstance(v, dict):
                    sanitized[k] = {
                        pk: GeminiAdapter._sanitize_schema(pv)
                        for pk, pv in v.items()
                        if isinstance(pv, dict)
                    }
                elif k == "items" and isinstance(v, dict):
                    sanitized[k] = GeminiAdapter._sanitize_schema(v)
                else:
                    sanitized[k] = v

        if "type" not in sanitized:
            sanitized["type"] = "object" if "properties" in sanitized else "string"

        return sanitized

    @classmethod
    def _build_tools(cls, tools: list[ToolDefinition]) -> list[dict]:
        """Convert Harma ToolDefinition list to Gemini function declarations."""
        decls = []
        for t in tools:
            name = t.name if hasattr(t, "name") else t.get("name")
            desc = t.description if hasattr(t, "description") else t.get("description", "")
            params = t.parameters if hasattr(t, "parameters") else t.get("parameters", {})
            decls.append({
                "name": name,
                "description": desc,
                "parameters": cls._sanitize_schema(params),
            })
        return [{"function_declarations": decls}]

    def _build_model(self, system: Optional[str], tools: Optional[list]):
        gen_config = self._genai.GenerationConfig(
            temperature=self._temperature,
            max_output_tokens=self._max_tokens,
        )
        default_inst = "You are Harma, an action-oriented personal AI agent. Accomplish tasks directly using available tools."
        sys_instruction = system.strip() if (system and system.strip()) else default_inst
        return self._genai.GenerativeModel(
            model_name=self._model_name,
            generation_config=gen_config,
            system_instruction=sys_instruction,
            tools=self._build_tools(tools) if tools else None,
        )

    # ── Core API ──────────────────────────────────────────────────────────────

    async def complete(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDefinition]] = None,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        # Try each available key in the pool (healthy prioritized) before giving up
        ordered_keys = self._get_ordered_keys()
        attempts = len(ordered_keys)
        last_exc: Optional[Exception] = None

        # If all Gemini keys are on active cooldown and Groq is available, route to Groq immediately
        now = time.time()
        all_cooling = all(_KEY_COOLDOWNS.get(k, 0) > now for k in ordered_keys)
        if all_cooling and config.llm.groq_keys:
            try:
                log.info("[GEMINI] All Gemini keys currently on cooldown — routing to Groq immediately.")
                if getattr(self, "_fallback_provider", None) is None:
                    from harma.llm.adapters.groq_adapter import GroqAdapter
                    self._fallback_provider = GroqAdapter()
                return await self._fallback_provider.complete(
                    messages=messages,
                    tools=tools,
                    system=system,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as fb_exc:
                log.error("[GEMINI] Fast fallback to Groq failed: %s", fb_exc)

        for attempt, curr_key in enumerate(ordered_keys):
            self._configure_key(curr_key)
            self._active_key = curr_key
            try:
                return await self._do_complete(messages, tools, system, temperature, max_tokens)
            except Exception as exc:
                is_rotatable = self._is_rotatable_error(exc)
                msg_lower = str(exc).lower()
                is_invalid = "api_key_invalid" in msg_lower or "api key not valid" in msg_lower

                if is_invalid:
                    _INVALID_KEYS.add(curr_key)
                    self._drop_invalid_key(curr_key)
                elif is_rotatable:
                    _KEY_COOLDOWNS[curr_key] = time.time() + 300  # 5 min cooldown

                if is_rotatable and attempt < attempts - 1:
                    log.warning(
                        "[GEMINI] Key hit error (%s) — rotating to next key in pool.",
                        exc,
                    )
                    last_exc = exc
                elif not is_rotatable:
                    log.error("[GEMINI] Request failed with non-rotatable error: %s", exc)
                    return LLMResponse(content=f"[Gemini error: {exc}]", finish_reason="error")
                else:
                    last_exc = exc

        log.warning("[GEMINI] All %d Gemini keys exhausted (quota/limits). Checking Groq fallback...", attempts)
        if config.llm.groq_keys:
            try:
                log.info("[GEMINI] Seamlessly falling back to Groq provider.")
                if getattr(self, "_fallback_provider", None) is None:
                    from harma.llm.adapters.groq_adapter import GroqAdapter
                    self._fallback_provider = GroqAdapter()
                return await self._fallback_provider.complete(
                    messages=messages,
                    tools=tools,
                    system=system,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as fb_exc:
                log.error("[GEMINI] Fallback to Groq failed: %s", fb_exc)

        log.error("[GEMINI] All %d keys exhausted. Last error: %s", attempts, last_exc)
        return LLMResponse(content=f"[Gemini error: all keys exhausted — {last_exc}]", finish_reason="error")

    async def _do_complete(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDefinition]],
        system: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> LLMResponse:
        base_inst = "You are Harma, an action-oriented personal AI agent. Accomplish tasks directly using available tools."
        extra = ""
        if system:
            lines = [
                line for line in system.splitlines()
                if "### USER CONTEXT" in line or "Memory" in line or "Plan" in line or "Context" in line
            ]
            if lines:
                extra = "\n" + "\n".join(lines[:10])
        sys_inst = base_inst + extra
        model = self._build_model(sys_inst, tools)

        # Convert messages into contents suitable for Gemini generate_content
        contents = []
        for msg in messages:
            role = "user" if msg.role in (Role.USER, Role.TOOL) else "model"
            text = (msg.content or "").strip()
            if not text:
                if msg.tool_calls:
                    names = ", ".join([tc.name for tc in msg.tool_calls if tc.name])
                    text = f"Action: executing {names}" if names else "Action: executing tools"
                elif msg.tool_results:
                    valid_res = [tr.content.strip() for tr in msg.tool_results if tr.content and tr.content.strip()]
                    text = f"Tool result: {', '.join(valid_res)}" if valid_res else "Tool completed successfully."
                else:
                    text = "Continue"

            text = text.strip() or "Continue"

            # Merge with previous turn if same role (Gemini requires strictly alternating roles)
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"].append(text)
            else:
                contents.append({"role": role, "parts": [text]})

        if not contents:
            contents = [{"role": "user", "parts": ["Hello"]}]

        response = await asyncio.to_thread(model.generate_content, contents)

        content = ""
        tool_calls: list[ToolCall] = []

        try:
            candidates = getattr(response, "candidates", [])
            if candidates and hasattr(candidates[0], "content") and hasattr(candidates[0].content, "parts"):
                for part in candidates[0].content.parts:
                    if hasattr(part, "text") and part.text:
                        content += part.text
                    if hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        tool_calls.append(
                            ToolCall(
                                id=str(uuid.uuid4()),
                                name=fc.name,
                                arguments=dict(fc.args) if hasattr(fc, "args") else {},
                            )
                        )
            elif hasattr(response, "text") and response.text:
                content = response.text
        except Exception as parse_exc:
            log.debug("[GEMINI] Response parts extraction fallback: %s", parse_exc)
            if hasattr(response, "text"):
                try:
                    content = response.text
                except Exception:
                    content = ""

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else "stop",
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
            self._configure_key(self._active_key)
            models = await asyncio.to_thread(self._genai.list_models)
            return True
        except Exception as exc:
            log.warning("[GEMINI] Health check failed: %s", exc)
            return False
