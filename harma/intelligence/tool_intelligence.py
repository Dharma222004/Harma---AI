"""
Harma Tool Selection Intelligence

Provides structured capability modeling and capability-based tool matching,
enabling Harma to select tools based on function rather than hardcoded names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from harma.config.logging_config import get_logger
from harma.intelligence.plan_models import RiskLevel
from harma.tools.base import BaseTool

log = get_logger(__name__)


class ToolCapability(str, Enum):
    """Normalized functional capabilities of tools."""
    COMMUNICATION = "communication"  # Messaging, email, alerts
    READ_DATA = "read_data"          # Search, fetch, read, inspect
    WRITE_DATA = "write_data"        # Create, modify, write
    DELETE_DATA = "delete_data"      # Delete, remove, purge
    FILE_SYSTEM = "file_system"      # Local files and directories
    NAVIGATION = "navigation"        # Web URLs, app switching, menus
    SYSTEM_CONTROL = "system_control"# Windows, processes, time, info
    BROWSER = "browser"              # Web automation
    VISION = "vision"                # Screen/image inspection
    DEVICE = "device"                # Android/mobile interaction
    INTEGRATION = "integration"      # External MCP tools


@dataclass
class ToolMetadata:
    """Enhanced metadata for tool intelligence and planning."""
    name: str
    description: str
    capabilities: list[ToolCapability]
    risk_level: RiskLevel = RiskLevel.SAFE
    data_sensitivity: str = "public"
    side_effects: bool = False
    idempotent: bool = True
    input_schema: dict[str, Any] = field(default_factory=dict)


class ToolIntelligence:
    """
    Infers capability and risk metadata for any tool in the registry,
    and provides semantic capability matching.
    """

    @staticmethod
    def infer_metadata(tool: BaseTool) -> ToolMetadata:
        """
        Derive capabilities and risk level from tool name, description, and permission level.
        """
        name = tool.name.lower()
        desc = tool.description.lower()
        caps: list[ToolCapability] = []

        # Infer capabilities
        if any(w in name or w in desc for w in ["email", "message", "slack", "notify", "sms", "chat", "send"]):
            caps.append(ToolCapability.COMMUNICATION)
        if any(w in name or w in desc for w in ["search", "get", "list", "read", "fetch", "check"]):
            caps.append(ToolCapability.READ_DATA)
        if any(w in name or w in desc for w in ["create", "add", "insert", "update", "set", "write"]):
            caps.append(ToolCapability.WRITE_DATA)
        if any(w in name or w in desc for w in ["delete", "remove", "drop", "close"]):
            caps.append(ToolCapability.DELETE_DATA)
        if any(w in name or w in desc for w in ["file", "dir", "directory", "folder", "path"]):
            caps.append(ToolCapability.FILE_SYSTEM)
        if any(w in name or w in desc for w in ["browser", "page", "url", "click", "navigate", "dom"]):
            caps.append(ToolCapability.BROWSER)
            caps.append(ToolCapability.NAVIGATION)
        if any(w in name or w in desc for w in ["screen", "vision", "screenshot", "ocr", "observe"]):
            caps.append(ToolCapability.VISION)
        if any(w in name or w in desc for w in ["android", "mobile", "device", "tap", "swipe"]):
            caps.append(ToolCapability.DEVICE)
        if "." in name:
            caps.append(ToolCapability.INTEGRATION)

        if not caps:
            caps.append(ToolCapability.SYSTEM_CONTROL)

        # Risk level mapping from permission level
        perm_val = getattr(tool.permission_level, "value", str(tool.permission_level)).lower()
        if "high" in perm_val:
            risk = RiskLevel.HIGH_RISK
        elif "sensitive" in perm_val:
            risk = RiskLevel.SENSITIVE
        else:
            risk = RiskLevel.SAFE

        side_effects = (
            ToolCapability.WRITE_DATA in caps
            or ToolCapability.DELETE_DATA in caps
            or ToolCapability.COMMUNICATION in caps
            or risk in (RiskLevel.SENSITIVE, RiskLevel.HIGH_RISK)
        )
        idempotent = ToolCapability.READ_DATA in caps or ToolCapability.VISION in caps

        return ToolMetadata(
            name=tool.name,
            description=tool.description,
            capabilities=caps,
            risk_level=risk,
            side_effects=side_effects,
            idempotent=idempotent,
            input_schema=getattr(tool, "parameters", {}),
        )

    @classmethod
    def match_tools_by_intent(
        cls,
        intent: str,
        available_tools: list[BaseTool],
        limit: int = 5,
    ) -> list[BaseTool]:
        """
        Find candidate tools for an intent based on semantic keyword and capability match.
        """
        low_intent = intent.lower()
        scored: list[tuple[float, BaseTool]] = []

        for tool in available_tools:
            meta = cls.infer_metadata(tool)
            score = 0.0

            # Match capability keywords
            for cap in meta.capabilities:
                if cap.value in low_intent:
                    score += 2.0

            # Match tool name tokens
            for token in tool.name.replace(".", "_").split("_"):
                if len(token) > 2 and token in low_intent:
                    score += 1.5

            # Match description words
            for desc_word in tool.description.lower().split():
                if len(desc_word) > 3 and desc_word in low_intent:
                    score += 0.2

            if score > 0:
                scored.append((score, tool))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [tool for _, tool in scored[:limit]]
