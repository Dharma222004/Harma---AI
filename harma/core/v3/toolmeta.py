"""
Harma Runtime V3 — Tool metadata helpers

Derives side-effect, domain, resource and risk information for any registered tool from
the existing router index (`TOOL_DOMAIN_INDEX`) and the tool's declared permission level.
Unknown tools (e.g. dynamically-registered MCP tools) get conservative defaults.
"""

from __future__ import annotations

from typing import Any, Optional

from harma.core.execution_state import _CONSEQUENTIAL_TOOLS
from harma.core.router import TOOL_DOMAIN_INDEX, ToolDomain, ToolMetadata

# Tools the router index files under state-changing capabilities but which only read state.
_EXPLICIT_READ_ONLY: frozenset[str] = frozenset({
    "get_current_time", "get_system_info", "get_screen_size", "take_screenshot",
    "list_open_windows", "get_active_window", "observe_screen", "find_ui_element",
    "browser_status", "get_current_url", "get_page_title", "observe_page", "extract_page_text",
    "find_text_on_page", "extract_links", "get_element_text", "find_element",
    "list_browser_tabs", "list_browser_downloads",
    "android.observe_screen", "android.screenshot", "android.current_app", "android.list_apps",
    "android.notifications", "android.get_clipboard", "android.device_status",
    "tasks.list", "tasks.get", "tasks.history",
    "integrations.list", "integrations.status", "integrations.tools", "integrations.search_tools",
    "memory_recall", "memory_search", "memory_list", "memory_stats",
    "recall_memory", "search_memory", "get_all_memories", "list_tasks", "get_task_status",
    "read_file", "calculate", "list_directory",
    "plan_goal", "get_plan_status", "perceive_screen", "parse_document", "extract_structured_data",
})

# Read-only tools whose output is itself a complete, user-facing answer.
SELF_DESCRIBING: frozenset[str] = frozenset({
    "get_current_time", "get_system_info", "get_screen_size", "take_screenshot",
})

_READ_PREFIXES = ("get_", "list_", "read_", "fetch_", "describe_", "lookup_", "query_")

_SPEC_DOMAIN = {
    ToolDomain.SYSTEM: "system",
    ToolDomain.COMPUTER_APP: "computer",
    ToolDomain.COMPUTER_INTERACT: "computer",
    ToolDomain.BROWSER: "browser",
    ToolDomain.MEMORY: "memory",
    ToolDomain.ANDROID: "android",
    ToolDomain.TASKS: "scheduled_tasks",
    ToolDomain.INTEGRATIONS: "mcp",
    ToolDomain.INTELLIGENCE: "productivity",
}


def tool_meta(name: str) -> Optional[ToolMetadata]:
    return TOOL_DOMAIN_INDEX.get(name)


def domain_of(name: str) -> str:
    meta = tool_meta(name)
    if meta:
        return _SPEC_DOMAIN.get(meta.domain, "system")
    if name.startswith("android."):
        return "android"
    if name.startswith(("browser_", "navigate", "search_web")):
        return "browser"
    if name.startswith(("memory", "recall_", "search_memory")):
        return "memory"
    if name.startswith(("tasks.", "schedule")):
        return "scheduled_tasks"
    if any(k in name for k in ("send_", "email", "message", "post_")):
        return "communication"
    if any(k in name for k in ("file", "directory")):
        return "files"
    return "mcp"


def is_read_only(name: str, tool: Any = None) -> bool:
    if name in _EXPLICIT_READ_ONLY:
        return True
    meta = tool_meta(name)
    if meta:
        return meta.side_effect_level in ("none", "read_only")
    if name in _CONSEQUENTIAL_TOOLS:
        return False
    level = _perm_value(tool)
    short = name.split(".")[-1]
    return level == "safe" and short.startswith(_READ_PREFIXES)


def _perm_value(tool: Any) -> str:
    lvl = getattr(tool, "permission_level", None)
    return str(getattr(lvl, "value", lvl or "safe")).lower()


def is_consequential(name: str, tool: Any = None) -> bool:
    """Side effects that must never be blindly repeated (send / delete / submit / purchase ...)."""
    if name in _CONSEQUENTIAL_TOOLS:
        return True
    meta = tool_meta(name)
    if meta and meta.side_effect_level == "consequential":
        return True
    if is_read_only(name, tool):
        return False
    return _perm_value(tool) in ("sensitive", "high_risk")


def risk_of(name: str, tool: Any = None) -> str:
    lvl = _perm_value(tool)
    if lvl == "high_risk":
        return "high"
    meta = tool_meta(name)
    risk = meta.risk_level if meta else "medium"
    if lvl == "sensitive" or is_consequential(name, tool):
        return "high" if risk == "high" else "medium"
    return risk


def resource_for(name: str, tool: Any = None) -> Optional[str]:
    """Exclusive resource a state-changing tool needs (None for read-only tools)."""
    if is_read_only(name, tool):
        return None
    meta = tool_meta(name)
    if meta:
        if meta.domain in (ToolDomain.COMPUTER_APP, ToolDomain.COMPUTER_INTERACT):
            return "desktop_input"
        if meta.domain == ToolDomain.BROWSER:
            return "browser_session"
        if meta.domain == ToolDomain.ANDROID:
            return "android_device"
        if meta.domain == ToolDomain.INTEGRATIONS:
            return "mcp"
        return None
    if name.startswith("android."):
        return "android_device"
    if name.startswith(("mcp.", "integrations.")) or "." in name:
        return "mcp"
    return None


_RISK_RANK = {"low": 0, "medium": 1, "high": 2}


def max_risk(levels: list[str]) -> str:
    best = "low"
    for lv in levels:
        if _RISK_RANK.get(lv, 1) > _RISK_RANK[best]:
            best = lv
    return best


def humanize_step(tool: str, arguments: dict[str, Any]) -> str:
    """Short deterministic description such as 'open application (Notepad)'."""
    label = tool.split(".")[-1].replace("_", " ")
    vals = [str(v) for v in (arguments or {}).values() if isinstance(v, (str, int, float)) and str(v).strip()]
    if vals:
        main = vals[0]
        if len(main) > 60:
            main = main[:57] + "..."
        return f"{label} ({main})"
    return label


def required_params(tool: Any) -> list[str]:
    params = getattr(tool, "parameters", None) or {}
    req = params.get("required") if isinstance(params, dict) else None
    return list(req or [])


def first_string_param(tool: Any) -> Optional[str]:
    """Primary string parameter of a tool's schema (required first)."""
    params = getattr(tool, "parameters", None) or {}
    props = params.get("properties", {}) if isinstance(params, dict) else {}
    for name in required_params(tool):
        if props.get(name, {}).get("type", "string") == "string":
            return name
    for name, spec in props.items():
        if isinstance(spec, dict) and spec.get("type", "string") == "string":
            return name
    return None
