"""
Harma Model Router & Provider Fallback

Routes model completions by functional role (Fast, Reasoning, Vision, Extraction)
while ensuring HarmaAgent remains the single central reasoning brain.
Implements automatic primary-to-fallback failover.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from harma.config.logging_config import get_logger
from harma.llm.provider import LLMProvider, LLMResponse, Message, ToolDefinition

log = get_logger(__name__)


class ModelRole(str, Enum):
    """Functional model roles for cost/latency optimization."""
    FAST_MODEL = "fast"            # Quick classification, extraction, validation
    REASONING_MODEL = "reasoning"  # Multi-step planning, analysis, synthesis
    VISION_MODEL = "vision"        # Multimodal image & screenshot perception
    EXTRACTION_MODEL = "extraction"# Schema-constrained data extraction


class ModelRouter:
    """
    Directs LLM requests based on task role with resilient fallback.
    """

    def __init__(
        self,
        primary_provider: LLMProvider,
        fallback_provider: Optional[LLMProvider] = None,
    ) -> None:
        self.primary = primary_provider
        self.fallback = fallback_provider
        self.route_stats: dict[str, int] = {r.value: 0 for r in ModelRole}
        self.failover_count: int = 0

    def select_role(self, task_type: str) -> ModelRole:
        """Map task type to a ModelRole."""
        low = task_type.lower()
        if "vision" in low or "screenshot" in low or "image" in low:
            return ModelRole.VISION_MODEL
        if "extract" in low or "schema" in low:
            return ModelRole.EXTRACTION_MODEL
        if "plan" in low or "complex" in low or "reason" in low:
            return ModelRole.REASONING_MODEL
        return ModelRole.FAST_MODEL

    async def complete(
        self,
        messages: list[Message],
        role: ModelRole = ModelRole.REASONING_MODEL,
        tools: Optional[list[ToolDefinition]] = None,
        system: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Execute completion with selected role, automatically failing over to fallback on error.
        """
        self.route_stats[role.value] += 1
        log.info("[ROUTER] Routing request for role '%s' to primary provider '%s'", role.value, self.primary.name)

        try:
            response = await self.primary.complete(
                messages=messages,
                tools=tools,
                system=system,
                **kwargs,
            )
            return response
        except Exception as exc:
            log.warning("[ROUTER] Primary provider '%s' failed: %s", self.primary.name, exc)
            if self.fallback:
                log.info("[ROUTER] Failing over to fallback provider '%s'", self.fallback.name)
                self.failover_count += 1
                try:
                    return await self.fallback.complete(
                        messages=messages,
                        tools=tools,
                        system=system,
                        **kwargs,
                    )
                except Exception as fb_exc:
                    log.error("[ROUTER] Fallback provider '%s' also failed: %s", self.fallback.name, fb_exc)
                    raise fb_exc
            raise exc
