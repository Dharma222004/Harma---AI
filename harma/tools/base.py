"""
Harma Tool Base

All tools in the system inherit from BaseTool.

Design:
  • Each tool is a self-contained class.
  • Tools declare their own name, description, parameters, and permission level.
  • The ToolRegistry discovers and exposes them to the agent.
  • Adding a new tool never requires touching agent or LLM code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PermissionLevel(str, Enum):
    """
    Permission tiers used by the security layer.

    SAFE       — auto-execute (read-only, low-risk)
    SENSITIVE  — confirm when configured (e.g. send message)
    HIGH_RISK  — always confirm explicitly (destructive / financial)
    """
    SAFE = "safe"
    SENSITIVE = "sensitive"
    HIGH_RISK = "high_risk"


@dataclass
class ToolResult:
    """
    Standardised return value from every tool.

    success  — True if the tool completed its intended action.
    output   — String representation of the result for the LLM.
    data     — Optional structured data for further processing.
    error    — Human-readable error message if success is False.
    """
    success: bool
    output: str
    data: Any = None
    error: str = ""

    def __str__(self) -> str:
        if self.success:
            return self.output
        return f"[ERROR] {self.error}"


class BaseTool(ABC):
    """
    Abstract base class every Harma tool must implement.

    Subclasses are registered automatically by the ToolRegistry.
    """

    # ── Class-level attributes to override in subclasses ──────────────────────

    name: str = ""
    """Unique snake_case tool identifier. Used in LLM tool definitions."""

    description: str = ""
    """Clear, single-paragraph description used verbatim in the LLM prompt."""

    permission_level: PermissionLevel = PermissionLevel.SAFE
    """Default permission level for this tool."""

    parameters: dict[str, Any] = field(default_factory=dict)
    """
    JSON Schema object describing the tool's input parameters.

    Example:
        {
            "type": "object",
            "properties": {
                "application_name": {
                    "type": "string",
                    "description": "Name of the application to open."
                }
            },
            "required": ["application_name"]
        }
    """

    # ── Abstract interface ────────────────────────────────────────────────────

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute the tool with the provided arguments.

        Args:
            **kwargs: Arguments matching the tool's ``parameters`` schema.

        Returns:
            ToolResult indicating success/failure and the result text.
        """

    # ── Helpers ───────────────────────────────────────────────────────────────

    def to_definition(self) -> dict[str, Any]:
        """
        Return a dict compatible with LLM tool-definition format.
        Used internally by the registry.
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def __repr__(self) -> str:
        return f"<Tool name={self.name!r} permission={self.permission_level.value}>"
