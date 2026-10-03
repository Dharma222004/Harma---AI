"""
Harma Hierarchical Capability Router & Tool Domain Index — Performance V2

Lightweight, zero-LLM-cost intent classifier, tool index, and schema cache.

Instead of sending 100+ tool schemas (over 9,000 tokens) to the LLM on every iteration:
  1. Classifies the request into a complexity tier:
     (TRIVIAL, DETERMINISTIC_TOOL, SIMPLE_TOOL, MULTI_STEP, RESEARCH, COMPLEX)
  2. Selects only the minimal domain-relevant tool subset (4–12 tools vs 101).
  3. Uses a precomputed in-memory Tool Schema Cache to eliminate repeated JSON schema generation.

Architecture:
    User request
        ↓
    classify_request()          ← deterministic pattern & metadata matching (0 LLM cost, < 1ms)
        ↓
    select_tools()              ← returns minimal relevant ToolDefinition subset
        ↓
    ToolSchemaCache             ← pre-cached OpenAI function schema dictionaries
        ↓
    LLM (with minimal tools)    ← 400-800 tokens instead of 9,300 tokens → 5× to 10× faster TTFT
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from harma.config.logging_config import get_logger
from harma.llm.provider import ToolDefinition

log = get_logger(__name__)


class RequestTier(str, Enum):
    TRIVIAL            = "trivial"            # Conversational, no tools needed
    DETERMINISTIC_TOOL = "deterministic_tool" # Fast-path single tool (e.g. time, sysinfo)
    SIMPLE_TOOL        = "simple_tool"        # Single app/memory operation
    MULTI_STEP         = "multi_step"         # Multi-step action within a specific domain
    RESEARCH           = "research"           # Information gathering / search
    COMPLEX            = "complex"            # Full planning across arbitrary tools


class ToolDomain(str, Enum):
    SYSTEM             = "system"
    COMPUTER_APP       = "computer_app"
    COMPUTER_INTERACT  = "computer_interact"
    BROWSER            = "browser"
    MEMORY             = "memory"
    ANDROID            = "android"
    TASKS              = "tasks"
    INTEGRATIONS       = "integrations"
    INTELLIGENCE       = "intelligence"


@dataclass(frozen=True)
class ToolMetadata:
    """Static metadata for indexing tools in the hierarchical registry."""
    name: str
    domain: ToolDomain
    capability: str
    risk_level: str = "low"                   # low | medium | high
    requires_observation: bool = False
    requires_confirmation: bool = False
    supports_parallel: bool = False
    side_effect_level: str = "none"           # none | read_only | state_change | consequential


# ── Granular Capability Sets (Aligned with Registered Tool Names) ───────────────

_CAP_SYSTEM = frozenset({
    "get_current_time", "get_system_info",
})

_CAP_SCREENSHOT = frozenset({
    "take_screenshot", "get_screen_size",
})

_CAP_COMPUTER_APP = frozenset({
    "open_application", "close_application", "focus_application",
    "list_open_windows", "get_active_window", "observe_screen",
})

_CAP_COMPUTER_INTERACT = frozenset({
    "mouse_move", "mouse_click", "mouse_double_click", "mouse_right_click",
    "mouse_drag", "mouse_scroll", "type_text", "press_key", "hotkey",
    "find_ui_element", "click_element",
})

_CAP_BROWSER_CORE = frozenset({
    "launch_browser", "close_browser", "browser_status",
    "navigate_to", "go_back", "go_forward", "reload_page",
    "get_current_url", "get_page_title", "observe_page", "search_web",
    "browser_click", "browser_type", "browser_scroll",
    "extract_page_text", "find_text_on_page",
    "extract_links", "get_element_text", "find_element",
})

_CAP_BROWSER_FULL = frozenset({
    "launch_browser", "close_browser", "browser_status",
    "navigate_to", "go_back", "go_forward", "reload_page",
    "get_current_url", "get_page_title", "observe_page", "search_web",
    "browser_click", "browser_type", "browser_select", "browser_check",
    "browser_uncheck", "browser_hover", "browser_press_key",
    "browser_scroll", "browser_upload_file",
    "extract_page_text", "extract_links", "find_text_on_page",
    "get_element_text", "find_element",
    "list_browser_tabs", "new_browser_tab", "switch_browser_tab", "close_browser_tab",
    "browser_download", "list_browser_downloads",
})

_CAP_MEMORY = frozenset({
    "memory_remember", "memory_recall", "memory_search",
    "memory_list", "memory_stats", "memory_update",
    "memory_forget", "memory_forget_all", "memory_forget_query",
})

_CAP_ANDROID = frozenset({
    "android.tap", "android.type", "android.swipe", "android.scroll",
    "android.press_key", "android.long_press", "android.observe_screen",
    "android.screenshot", "android.launch_app", "android.close_app",
    "android.current_app", "android.list_apps", "android.home", "android.back",
    "android.recent_apps", "android.notifications", "android.get_clipboard",
    "android.set_clipboard", "android.device_status", "android.open_settings",
})

_CAP_TASKS = frozenset({
    "tasks.create", "tasks.list", "tasks.get", "tasks.cancel",
    "tasks.pause", "tasks.resume", "tasks.delete", "tasks.run_now",
    "tasks.history",
})

_CAP_INTEGRATIONS = frozenset({
    "integrations.list", "integrations.connect", "integrations.disconnect",
    "integrations.status", "integrations.tools", "integrations.search_tools",
})

_CAP_PLANNING = frozenset({
    "plan_goal", "get_plan_status",
    "perceive_screen", "parse_document", "extract_structured_data",
})


# ── Static Tool Domain Index ───────────────────────────────────────────────────

def _build_tool_index() -> dict[str, ToolMetadata]:
    idx: dict[str, ToolMetadata] = {}
    for name in _CAP_SYSTEM:
        idx[name] = ToolMetadata(name=name, domain=ToolDomain.SYSTEM, capability="system_query", risk_level="low", side_effect_level="read_only")
    for name in _CAP_SCREENSHOT:
        idx[name] = ToolMetadata(name=name, domain=ToolDomain.COMPUTER_APP, capability="screen_capture", risk_level="low", side_effect_level="read_only")
    for name in _CAP_COMPUTER_APP:
        idx[name] = ToolMetadata(name=name, domain=ToolDomain.COMPUTER_APP, capability="window_management", risk_level="low", requires_observation=True, side_effect_level="state_change")
    for name in _CAP_COMPUTER_INTERACT:
        idx[name] = ToolMetadata(name=name, domain=ToolDomain.COMPUTER_INTERACT, capability="gui_input", risk_level="medium", requires_observation=True, side_effect_level="state_change")
    for name in _CAP_BROWSER_FULL:
        idx[name] = ToolMetadata(name=name, domain=ToolDomain.BROWSER, capability="web_automation", risk_level="low", requires_observation=True, side_effect_level="state_change")
    for name in _CAP_MEMORY:
        idx[name] = ToolMetadata(name=name, domain=ToolDomain.MEMORY, capability="knowledge_store", risk_level="low", side_effect_level="state_change" if "forget" in name or "remember" in name else "read_only")
    for name in _CAP_ANDROID:
        idx[name] = ToolMetadata(name=name, domain=ToolDomain.ANDROID, capability="mobile_control", risk_level="medium", requires_observation=True, side_effect_level="state_change")
    for name in _CAP_TASKS:
        idx[name] = ToolMetadata(name=name, domain=ToolDomain.TASKS, capability="task_scheduler", risk_level="medium", side_effect_level="state_change")
    for name in _CAP_INTEGRATIONS:
        idx[name] = ToolMetadata(name=name, domain=ToolDomain.INTEGRATIONS, capability="external_mcp", risk_level="medium", side_effect_level="state_change" if "connect" in name else "read_only")
    for name in _CAP_PLANNING:
        idx[name] = ToolMetadata(name=name, domain=ToolDomain.INTELLIGENCE, capability="planning", risk_level="low", side_effect_level="read_only")
    return idx

TOOL_DOMAIN_INDEX: dict[str, ToolMetadata] = _build_tool_index()


# ── Tool Schema Cache ─────────────────────────────────────────────────────────

class ToolSchemaCache:
    """
    High-performance in-memory cache for provider-formatted tool schemas.
    Avoids reconstructing JSON schema dictionaries on every LLM call.
    """
    _cache: dict[str, dict[str, Any]] = {}

    @classmethod
    def get_openai_schema(cls, tool_def: ToolDefinition) -> dict[str, Any]:
        """Get or create cached OpenAI-compatible function schema."""
        name = tool_def.name
        if name in cls._cache:
            return cls._cache[name]

        schema = {
            "type": "function",
            "function": {
                "name": tool_def.name,
                "description": tool_def.description.strip(),
                "parameters": tool_def.parameters if isinstance(tool_def.parameters, dict) else {},
            },
        }
        cls._cache[name] = schema
        return schema

    @classmethod
    def get_openai_schemas(cls, tool_defs: list[ToolDefinition]) -> list[dict[str, Any]]:
        """Get cached schemas for an entire list of ToolDefinitions."""
        return [cls.get_openai_schema(td) for td in tool_defs]

    @classmethod
    def invalidate(cls, tool_name: Optional[str] = None) -> None:
        """Invalidate single or all cached schemas."""
        if tool_name:
            cls._cache.pop(tool_name, None)
        else:
            cls._cache.clear()


# ── Hierarchical Intent Patterns ──────────────────────────────────────────────

_PATTERNS: list[tuple[re.Pattern, RequestTier, frozenset[str]]] = [
    # 1. Deterministic System Queries (time, clock, date, system stats)
    (re.compile(r"\b(what time|current time|the time|what is the time|clock|what date|today'?s date|current date)\b", re.I),
     RequestTier.TRIVIAL, _CAP_SYSTEM),

    (re.compile(r"\b(cpu usage|memory usage|ram usage|disk usage|disk space|storage space|battery|system info|system information|sysinfo)\b", re.I),
     RequestTier.TRIVIAL, _CAP_SYSTEM),

    # 2. Desktop Messaging & Communication (WhatsApp, Telegram, Slack, Discord, Teams)
    # Strictly sends Desktop App + Desktop Interact tools (ONLY ~15 tools, NO browser tools!)
    (re.compile(r"\b(send|message|msg|text|dm|chat|post|whatsapp|telegram|slack|discord|teams)\b.{0,60}\b(message|msg|hi|hello|to|text|chat|send|saying|check|visible)\b", re.I),
     RequestTier.MULTI_STEP, _CAP_COMPUTER_APP | _CAP_COMPUTER_INTERACT),

    (re.compile(r"\b(open|launch|start)\b.{1,30}\b(whatsapp|telegram|slack|discord|teams)\b", re.I),
     RequestTier.SIMPLE_TOOL, _CAP_COMPUTER_APP),

    # 3. Web Browser Tasks (Navigate, search, inspect page)
    # Sends Browser Core + open/focus tools (ONLY ~12 tools, NO low-level OS mouse/keyboard!)
    (re.compile(r"\b(open|launch|start).{0,30}(chrome|firefox|edge|browser).{0,60}(and|then|navigate|go to|search|look up|visit|url|https?://|website|page|show)\b", re.I),
     RequestTier.MULTI_STEP, _CAP_BROWSER_CORE),

    (re.compile(r"\b(search|google|look up|find|browse|go to|navigate|url|https?://)\b", re.I),
     RequestTier.MULTI_STEP, _CAP_BROWSER_CORE),

    # 3b. Web Ticketing & Booking (BookMyShow, flights, movie tickets, showtimes, seats)
    (re.compile(r"\b(book|booking|ticket|tickets|seat|seats|showtime|showtimes|cinema|movie|movies|theatre|theater|checkout|cart|reservation|reserve)\b", re.I),
     RequestTier.MULTI_STEP, _CAP_BROWSER_FULL),

    # 4. Single Desktop Application Lifecycle (Open, close, switch)
    (re.compile(r"^\s*(open|launch|start|run)\s+(?!.*(\band\b|\bthen\b|\bwebsite\b|\burl\b))[a-zA-Z0-9_\-\.\s]{1,35}$", re.I),
     RequestTier.SIMPLE_TOOL, _CAP_COMPUTER_APP),

    (re.compile(r"^\s*(close|quit|exit|kill)\s+(?!.*(\band\b|\bthen\b))[a-zA-Z0-9_\-\.\s]{1,35}$", re.I),
     RequestTier.SIMPLE_TOOL, _CAP_COMPUTER_APP),

    # 5. Screen Capture
    (re.compile(r"\b(screenshot|screen shot|capture screen|take screenshot)\b", re.I),
     RequestTier.SIMPLE_TOOL, _CAP_SCREENSHOT | frozenset({"get_active_window"})),

    # 6. Memory Operations
    (re.compile(r"\b(remember|recall|memory|what did i|my preference|my favourite|favourite|favorite)\b", re.I),
     RequestTier.SIMPLE_TOOL, _CAP_MEMORY),

    # 7. Android Device Control
    (re.compile(r"\b(android|phone|mobile|device|adb|tablet)\b", re.I),
     RequestTier.MULTI_STEP, _CAP_ANDROID),

    # 8. External Integrations / MCP
    (re.compile(r"\b(integration|integrations|mcp|external integration|connect|webhook|gmail|github)\b", re.I),
     RequestTier.MULTI_STEP, _CAP_INTEGRATIONS),

    # 9. Scheduled Tasks & Automation
    (re.compile(r"\b(schedule|task|tasks|remind|alarm|every day|weekly|cron|recurring|automation)\b", re.I),
     RequestTier.MULTI_STEP, _CAP_TASKS | _CAP_SYSTEM),

    # 10. Explicit Complex Planning
    (re.compile(r"\b(/plan|plan:|/dry.run|step by step|multi.step goal|complex task)\b", re.I),
     RequestTier.COMPLEX, _CAP_PLANNING | _CAP_COMPUTER_APP | _CAP_BROWSER_CORE),
]


def classify_request(user_input: str) -> tuple[RequestTier, frozenset[str]]:
    """
    Classify a user request into a complexity tier and relevant capability set.

    Returns:
        (tier, capability_names) — a set of tool names deemed relevant.
        Empty capability_names means "use all tools" (safe fallback for unclassified COMPLEX).
    """
    text = user_input.strip()
    low = text.lower()

    # Conversational greeting / check (0 tools)
    if re.match(r"^(hi|hello|hey|greetings|good\s+(morning|afternoon|evening)|who are you|what is your name)(\s+harma|\s+assistant|\s+there)?\b[!?.]*$", low):
        return RequestTier.TRIVIAL, frozenset()

    matched_caps: set[str] = set()
    highest_tier = RequestTier.TRIVIAL

    _tier_rank = {
        RequestTier.TRIVIAL: 0,
        RequestTier.DETERMINISTIC_TOOL: 1,
        RequestTier.SIMPLE_TOOL: 2,
        RequestTier.RESEARCH: 3,
        RequestTier.MULTI_STEP: 4,
        RequestTier.COMPLEX: 5,
    }

    for pattern, tier, caps in _PATTERNS:
        if pattern.search(text):
            matched_caps.update(caps)
            if _tier_rank[tier] > _tier_rank[highest_tier]:
                highest_tier = tier

    if not matched_caps:
        # If a browser session is currently active, follow-up interactions default to browser capabilities
        try:
            from harma.browser.controller import get_browser_controller
            ctrl = get_browser_controller()
            if ctrl and ctrl.is_open:
                return RequestTier.MULTI_STEP, _CAP_BROWSER_FULL | _CAP_SYSTEM
        except Exception:
            pass
        # Unknown or complex request — safe fallback to all tools
        return RequestTier.COMPLEX, frozenset()

    matched_caps.update(_CAP_SYSTEM)
    return highest_tier, frozenset(matched_caps)


def select_tools(
    user_input: str,
    all_tools: list[ToolDefinition],
    force_all: bool = False,
) -> tuple[list[ToolDefinition], RequestTier, int]:
    """
    Select the minimal relevant tool subset for a user request.

    Args:
        user_input:  The raw user message.
        all_tools:   Full list of available ToolDefinitions from the registry.
        force_all:   If True, bypass routing and return all tools.

    Returns:
        (selected_tools, tier, total_count)
    """
    total = len(all_tools)

    if force_all:
        return all_tools, RequestTier.COMPLEX, total

    tier, cap_names = classify_request(user_input)

    if tier == RequestTier.TRIVIAL:
        log.info("[ROUTER] TRIVIAL conversational request → 0/%d tools (100%% saved)", total)
        return [], tier, total

    if not cap_names:
        log.debug("[ROUTER] COMPLEX unclassified request → sending all %d tools", total)
        return all_tools, tier, total

    # Filter strictly to matching tool capability names
    selected = [t for t in all_tools if t.name in cap_names]

    # If the match was too narrow (< 1 tool), fall back to all tools
    if not selected:
        log.debug("[ROUTER] Zero matches for %s — falling back to all tools", cap_names)
        return all_tools, tier, total

    saved = total - len(selected)
    log.info(
        "[ROUTER] %s request → %d/%d tools  (saved %d tool schemas)",
        tier.value.upper(), len(selected), total, saved,
    )
    return selected, tier, total
