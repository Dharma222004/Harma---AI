"""
Harma Integrations — Permission Classification & Task Scope Enforcement

Maps external MCP tool capabilities to Harma's core PermissionLevel, validates
action consequences, and enforces integration and Phase 7 task allowlists.
"""

from __future__ import annotations

from typing import Optional

from harma.config.logging_config import get_logger
from harma.integrations.exceptions import IntegrationPermissionDeniedError
from harma.integrations.models import ToolCapability
from harma.tasks.models import AutonomyLevel
from harma.tools.base import PermissionLevel

log = get_logger(__name__)


class IntegrationPermissionPolicy:
    """Classifies external tools and enforces permission barriers."""

    # Default capability to PermissionLevel mapping
    CAPABILITY_PERMISSION_MAP = {
        ToolCapability.READ: PermissionLevel.SAFE,
        ToolCapability.CREATE: PermissionLevel.SENSITIVE,
        ToolCapability.UPDATE: PermissionLevel.SENSITIVE,
        ToolCapability.SEND: PermissionLevel.SENSITIVE,
        ToolCapability.DELETE: PermissionLevel.HIGH_RISK,
        ToolCapability.EXECUTE: PermissionLevel.HIGH_RISK,
        ToolCapability.ADMIN: PermissionLevel.HIGH_RISK,
    }

    @classmethod
    def infer_capability(cls, tool_name: str, description: str = "") -> ToolCapability:
        """Infer capability category from tool name naming conventions."""
        name_lower = tool_name.lower().split(".")[-1]  # remove namespace

        if any(name_lower.startswith(p) for p in ("list", "get", "search", "read", "fetch", "view", "find", "check")):
            return ToolCapability.READ
        if any(name_lower.startswith(p) for p in ("create", "add", "new", "insert", "post", "schedule")):
            return ToolCapability.CREATE
        if any(name_lower.startswith(p) for p in ("update", "edit", "modify", "patch", "set", "change")):
            return ToolCapability.UPDATE
        if any(name_lower.startswith(p) for p in ("send", "notify", "message", "email", "publish")):
            return ToolCapability.SEND
        if any(name_lower.startswith(p) for p in ("delete", "remove", "drop", "destroy", "cancel", "purge", "clear")):
            return ToolCapability.DELETE
        if any(name_lower.startswith(p) for p in ("run", "exec", "execute", "trigger", "launch")):
            return ToolCapability.EXECUTE
        if any(name_lower.startswith(p) for p in ("admin", "grant", "revoke", "transfer", "reset")):
            return ToolCapability.ADMIN

        # Default fallback: if write/destructive keywords in description
        desc_lower = description.lower()
        if "delete" in desc_lower or "destroy" in desc_lower:
            return ToolCapability.DELETE
        if "create" in desc_lower or "send" in desc_lower:
            return ToolCapability.CONFIRM if hasattr(ToolCapability, "CONFIRM") else ToolCapability.CREATE

        return ToolCapability.READ

    @classmethod
    def determine_permission_level(
        cls,
        tool_name: str,
        capability: Optional[ToolCapability] = None,
        description: str = "",
        explicit_override: Optional[PermissionLevel] = None,
    ) -> PermissionLevel:
        """Derive authoritative Harma PermissionLevel for an integration tool."""
        if explicit_override is not None:
            return explicit_override

        cap = capability or cls.infer_capability(tool_name, description)
        return cls.CAPABILITY_PERMISSION_MAP.get(cap, PermissionLevel.SENSITIVE)

    @classmethod
    def validate_task_execution(
        cls,
        tool_name: str,
        permission_level: PermissionLevel,
        task_allowed_tools: Optional[list[str]] = None,
        task_autonomy_level: Optional[AutonomyLevel] = None,
    ) -> None:
        """
        Validate whether a Phase 7 autonomous background task is authorized to invoke this tool.
        """
        # 1. Check explicit task allowlist
        if task_allowed_tools is not None and tool_name not in task_allowed_tools:
            log.warning("Task denied: %s not in allowed_tools %s", tool_name, task_allowed_tools)
            raise IntegrationPermissionDeniedError(
                f"Tool '{tool_name}' is not in task allowed_tools list.",
                tool_name=tool_name,
                required_level="allowlist",
            )

        # 2. Check task autonomy level constraints
        if task_autonomy_level == AutonomyLevel.LEVEL_1_REMINDER:
            if permission_level != PermissionLevel.SAFE and not tool_name.startswith("reminder."):
                raise IntegrationPermissionDeniedError(
                    f"Autonomy Level 1 (Reminder) cannot execute action tool '{tool_name}'.",
                    tool_name=tool_name,
                    required_level=permission_level.value,
                )

        elif task_autonomy_level == AutonomyLevel.LEVEL_2_READ_ONLY:
            if permission_level != PermissionLevel.SAFE:
                raise IntegrationPermissionDeniedError(
                    f"Autonomy Level 2 (Read-Only) cannot execute '{permission_level.value}' tool '{tool_name}'.",
                    tool_name=tool_name,
                    required_level=permission_level.value,
                )
