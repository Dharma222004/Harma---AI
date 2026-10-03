"""
LLM Provider Interface — Abstract base that every LLM adapter must implement.

Design goals:
  • Provider-agnostic: swap OpenAI ↔ Gemini ↔ Claude ↔ Ollama without
    touching any other Harma module.
  • Supports: system prompts, conversation history, tool definitions,
    tool calls, tool results, structured outputs, streaming.
  • Typed with dataclasses so call sites are self-documenting.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Shared data structures
# ─────────────────────────────────────────────────────────────────────────────

class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"           # tool-result messages


@dataclass
class ToolCall:
    """Represents a single tool-call request made by the LLM."""
    id: str                 # unique call id (provided by LLM or generated)
    name: str               # tool name
    arguments: dict[str, Any]  # parsed JSON arguments


@dataclass
class ToolResult:
    """Wraps the output of a tool so it can be fed back to the LLM."""
    tool_call_id: str
    name: str
    content: str            # serialised result (JSON string or plain text)
    is_error: bool = False


@dataclass
class Message:
    """A single message in a conversation."""
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    # name is used for tool-result messages to carry the tool's name
    name: Optional[str] = None


@dataclass
class ToolDefinition:
    """
    Describes a tool the LLM can invoke.

    The ``parameters`` dict follows the JSON Schema object format:
        {
            "type": "object",
            "properties": {
                "arg_name": {"type": "string", "description": "..."},
            },
            "required": ["arg_name"],
        }
    """
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""
    content: str                           # text reply (may be empty if tool calls present)
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"            # stop | tool_calls | length | error
    usage: dict[str, int] = field(default_factory=dict)   # prompt/completion tokens
    raw: Any = None                        # raw provider response for debugging


# ─────────────────────────────────────────────────────────────────────────────
# Abstract provider interface
# ─────────────────────────────────────────────────────────────────────────────

class LLMProvider(ABC):
    """
    Abstract base class for all LLM providers.

    Concrete implementations live in harma/llm/providers/.
    The agent always talks through this interface — never directly to an SDK.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name (e.g. 'OpenAI', 'Gemini')."""

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDefinition]] = None,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """
        Send messages to the LLM and return a complete response.

        Args:
            messages: Conversation history (not including system prompt).
            tools: Tool definitions the model may call.
            system: System instruction. Overrides provider default if given.
            temperature: Override provider default temperature.
            max_tokens: Override provider default max_tokens.

        Returns:
            LLMResponse with text content and/or tool_calls.
        """

    async def stream(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDefinition]] = None,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """
        Stream text tokens from the LLM.

        Default implementation falls back to complete() so providers only need
        to override this when they support native streaming.

        Yields:
            Text chunks as they arrive.
        """
        response = await self.complete(
            messages=messages,
            tools=tools,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        # Yield the full content as a single chunk for non-streaming providers
        if response.content:
            yield response.content

    async def health_check(self) -> bool:
        """
        Optional lightweight check to verify the provider is reachable.
        Returns True if healthy, False otherwise. Override in subclasses.
        """
        return True
