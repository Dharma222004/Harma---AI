"""
Harma Permission System

Enforces three-tier action permissions:
  SAFE       → auto-execute (no user confirmation needed)
  SENSITIVE  → ask user when auto_confirm_sensitive is False
  HIGH_RISK  → always ask (cannot be auto-confirmed)

The permission check is called by the executor BEFORE every tool call.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from harma.config.logging_config import get_logger
from harma.config.settings import config
from harma.tools.base import PermissionLevel

log = get_logger(__name__)


class PermissionDecision(str, Enum):
    ALLOWED = "allowed"
    DENIED = "denied"
    NEEDS_CONFIRMATION = "needs_confirmation"


class PermissionManager:
    """
    Decides whether a tool action is allowed to proceed automatically,
    or needs explicit user confirmation.
    """

    def __init__(self) -> None:
        self._cfg = config.permissions

    def check(
        self,
        tool_name: str,
        permission_level: PermissionLevel,
        context: Optional[str] = None,
    ) -> PermissionDecision:
        """
        Evaluate whether a tool at the given permission level can run.

        Args:
            tool_name: Name of the tool (for logging).
            permission_level: The tool's declared PermissionLevel.
            context: Optional description of what the tool is about to do.

        Returns:
            PermissionDecision
        """
        if permission_level == PermissionLevel.SAFE:
            if self._cfg.auto_confirm_safe:
                log.debug("Permission ALLOWED (safe auto): %s", tool_name)
                return PermissionDecision.ALLOWED
            return PermissionDecision.NEEDS_CONFIRMATION

        elif permission_level == PermissionLevel.SENSITIVE:
            if self._cfg.auto_confirm_sensitive:
                log.info("Permission ALLOWED (sensitive auto): %s", tool_name)
                return PermissionDecision.ALLOWED
            log.info("Permission NEEDS_CONFIRMATION (sensitive): %s", tool_name)
            return PermissionDecision.NEEDS_CONFIRMATION

        elif permission_level == PermissionLevel.HIGH_RISK:
            log.warning("Permission NEEDS_CONFIRMATION (high_risk): %s", tool_name)
            return PermissionDecision.NEEDS_CONFIRMATION

        return PermissionDecision.DENIED

    def build_confirmation_prompt(
        self,
        tool_name: str,
        permission_level: PermissionLevel,
        arguments: dict,
        context: Optional[str] = None,
    ) -> str:
        """Build a user-facing confirmation prompt for a pending tool call."""
        risk_label = {
            PermissionLevel.SAFE: "low-risk",
            PermissionLevel.SENSITIVE: "⚠  sensitive",
            PermissionLevel.HIGH_RISK: "🔴  HIGH RISK",
        }.get(permission_level, "unknown")

        lines = [
            f"Harma wants to run: [{risk_label}]  {tool_name}",
        ]
        if context:
            lines.append(f"Context: {context}")
        if arguments:
            lines.append("Arguments:")
            for k, v in arguments.items():
                lines.append(f"  {k}: {v}")
        lines.append("\nAllow? [y/N]")
        return "\n".join(lines)
