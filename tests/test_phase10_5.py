"""
Phase 10.5 Performance & Optimization Tests

Tests verify:
  1. Capability router correctly classifies and routes requests
  2. Tool schema caching works correctly
  3. Fast path generates correct responses without extra LLM calls
  4. Latency instrumentation captures all stages
  5. Performance stats endpoint works
  6. System prompt no longer mandates observe_screen after every action
  7. Context_fusion is skipped for TRIVIAL/SIMPLE_TOOL requests
  8. Selective tool loading reduces tool count for simple requests
"""

from __future__ import annotations

import asyncio
import time
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Router tests ──────────────────────────────────────────────────────────────


def test_router_classifies_open_app_as_simple_tool():
    from harma.core.router import classify_request, RequestTier
    tier, caps = classify_request("open Chrome on my desktop")
    assert tier in (RequestTier.SIMPLE_TOOL, RequestTier.MULTI_STEP), f"Expected SIMPLE_TOOL or MULTI_STEP, got {tier}"
    assert "open_application" in caps


def test_router_includes_system_tools_always():
    from harma.core.router import classify_request
    _, caps = classify_request("open Notepad")
    assert "get_current_time" in caps
    assert "get_system_info" in caps


def test_router_classifies_time_as_trivial():
    from harma.core.router import classify_request, RequestTier
    tier, caps = classify_request("what time is it?")
    assert tier == RequestTier.TRIVIAL
    assert "get_current_time" in caps


def test_router_classifies_browser_search_as_multistep():
    from harma.core.router import classify_request, RequestTier
    tier, caps = classify_request("search for OpenAI on Google")
    assert tier in (RequestTier.MULTI_STEP, RequestTier.SIMPLE_TOOL), f"Got {tier}"
    assert any("browser" in c or "search" in c or "navigate" in c for c in caps)


def test_router_select_tools_reduces_count():
    from harma.core.router import select_tools, RequestTier
    from harma.llm.provider import ToolDefinition

    # Build 50 fake tools spanning multiple categories
    all_tools = []
    for name in [
        "open_application", "close_application", "get_current_time", "get_system_info",
        "take_screenshot", "observe_screen", "mouse_click",
        "android.tap", "android.type", "android.launch_app",
        "browser_click", "navigate_to", "search_web",
        "memory_search", "memory_save",
        "tasks.create", "tasks.list",
        "integrations.list", "integrations.connect",
        "plan_goal", "get_plan_status",
    ] + [f"other_tool_{i}" for i in range(30)]:
        all_tools.append(ToolDefinition(
            name=name,
            description=f"Tool {name}",
            parameters={"type": "object", "properties": {}, "required": []}
        ))

    selected, tier, total = select_tools("open Chrome", all_tools)
    assert total == len(all_tools)
    assert len(selected) < total, f"Expected fewer tools than {total}, got {len(selected)}"
    assert any(t.name == "open_application" for t in selected)


def test_router_fallback_to_all_on_unrecognized():
    from harma.core.router import select_tools, RequestTier
    from harma.llm.provider import ToolDefinition

    all_tools = [
        ToolDefinition(name=f"tool_{i}", description=f"Tool {i}", parameters={})
        for i in range(10)
    ]
    selected, tier, total = select_tools("xyzzy gloop frob quantum entangle", all_tools)
    # Should fall back to all tools when unrecognized
    assert len(selected) == total or tier.value == "complex"


# ── Schema cache tests ────────────────────────────────────────────────────────


def test_registry_schema_cache_hit():
    """Second call returns cached result without rebuilding."""
    from harma.tools.registry import ToolRegistry
    from harma.tools.system.time_tools import GetCurrentTimeTool

    reg = ToolRegistry()
    reg.register(GetCurrentTimeTool())

    defs1 = reg.list_tool_definitions()
    defs2 = reg.list_tool_definitions()
    assert defs1 is defs2, "Expected same list object (cache hit)"


def test_registry_schema_cache_invalidated_on_register():
    """Cache invalidates when a new tool is registered."""
    from harma.tools.registry import ToolRegistry
    from harma.tools.system.time_tools import GetCurrentTimeTool, GetSystemInfoTool

    reg = ToolRegistry()
    reg.register(GetCurrentTimeTool())
    defs1 = reg.list_tool_definitions()

    reg.register(GetSystemInfoTool())  # should invalidate cache
    defs2 = reg.list_tool_definitions()

    assert len(defs2) == len(defs1) + 1
    assert defs1 is not defs2, "Expected new list (cache miss after registration)"


# ── Fast path tests ───────────────────────────────────────────────────────────


def test_fast_response_open_application():
    from harma.core.agent import _fast_response

    resp = _fast_response("open_application", {"application_name": "Chrome"}, "Opened Chrome.")
    assert "Chrome" in resp
    assert "Done" in resp or "opened" in resp.lower()


def test_fast_response_get_current_time():
    from harma.core.agent import _fast_response

    time_str = "Friday, 02 October 2026 06:00 PM India Standard Time"
    resp = _fast_response("get_current_time", {}, time_str)
    assert time_str in resp


def test_fast_response_take_screenshot():
    from harma.core.agent import _fast_response

    resp = _fast_response("take_screenshot", {}, "Screenshot saved to /tmp/screen.png")
    assert "screen.png" in resp or "Screenshot" in resp or "saved" in resp.lower() or "captured" in resp.lower()


# ── Latency instrumentation tests ─────────────────────────────────────────────


def test_trace_marks_stages():
    from harma.core.perf import RequestTrace, Stage

    trace = RequestTrace(request_id="test-001", user_input="test")
    trace.mark(Stage.LLM_REQUEST_START)
    time.sleep(0.01)
    trace.mark(Stage.LLM_REQUEST_END)
    trace.mark(Stage.API_RESPONSE)

    summary = trace.summary()
    assert summary["request_id"] == "test-001"
    assert summary["durations_ms"]["llm_ms"] is not None
    assert summary["durations_ms"]["llm_ms"] > 0
    assert summary["durations_ms"]["total_ms"] > 0


def test_trace_records_llm_calls_and_tokens():
    from harma.core.perf import RequestTrace, Stage

    trace = RequestTrace(request_id="test-002", user_input="test")
    trace.record_llm_call(tokens_in=500, tokens_out=100)
    trace.record_llm_call(tokens_in=200, tokens_out=50)

    summary = trace.summary()
    assert summary["counts"]["llm_calls"] == 2
    assert summary["counts"]["tokens_in"] == 700
    assert summary["counts"]["tokens_out"] == 150


def test_trace_tool_and_screenshot_counts():
    from harma.core.perf import RequestTrace, Stage

    trace = RequestTrace(request_id="test-003", user_input="test")
    trace.record_tool_call()
    trace.record_tool_call()
    trace.record_screenshot()

    summary = trace.summary()
    assert summary["counts"]["tool_calls"] == 2
    assert summary["counts"]["screenshots"] == 1


def test_perf_stats_aggregation():
    from harma.core.perf import RequestTrace, Stage, record_trace, get_performance_stats

    # Create and record several traces
    for i in range(5):
        t = RequestTrace(request_id=f"test-agg-{i}", user_input=f"test {i}")
        t.mark(Stage.LLM_REQUEST_START)
        time.sleep(0.005)
        t.mark(Stage.LLM_REQUEST_END)
        t.mark(Stage.API_RESPONSE)
        t.record_llm_call(tokens_in=100, tokens_out=50)
        record_trace(t)

    stats = get_performance_stats()
    assert stats["total_requests"] >= 5
    assert stats["total_latency"]["p50_ms"] is not None
    assert stats["per_request_avg"]["llm_calls"] is not None


# ── System prompt does not mandate observe_screen ─────────────────────────────


def test_system_prompt_no_mandatory_observe_after_open_app():
    from harma.core.prompt import HARMA_SYSTEM_PROMPT
    # Should NOT mandate observe_screen after every open_application
    assert "OBSERVE → ACT → OBSERVE" not in HARMA_SYSTEM_PROMPT
    # Should have efficiency rules
    assert "Efficiency" in HARMA_SYSTEM_PROMPT or "IMPORTANT" in HARMA_SYSTEM_PROMPT


def test_system_prompt_has_fast_path_guidance():
    from harma.core.prompt import HARMA_SYSTEM_PROMPT
    # Should have explicit guidance about NOT calling observe_screen unnecessarily
    prompt_lower = HARMA_SYSTEM_PROMPT.lower()
    assert "observe_screen" in prompt_lower
    assert "no" in prompt_lower or "not" in prompt_lower or "never" in prompt_lower


# ── Performance API endpoint test ─────────────────────────────────────────────


def test_get_performance_stats_structure():
    from harma.core.perf import get_performance_stats, RequestTrace, Stage, record_trace

    # Prime with at least one trace
    t = RequestTrace(request_id="api-test-001", user_input="open chrome")
    t.mark(Stage.LLM_REQUEST_START)
    t.mark(Stage.LLM_REQUEST_END)
    t.mark(Stage.API_RESPONSE)
    t.record_tool_call()
    record_trace(t)

    stats = get_performance_stats()
    assert "total_requests" in stats
    assert "total_latency" in stats
    assert "per_request_avg" in stats
    assert "recent_traces" in stats


# ── Compound intent and messaging routing tests ───────────────────────────────


def test_compound_intent_detection():
    from harma.core.agent import _has_compound_or_followup_intent

    # Single commands should NOT be flagged as compound
    assert not _has_compound_or_followup_intent("open whatsapp")
    assert not _has_compound_or_followup_intent("open Chrome")
    assert not _has_compound_or_followup_intent("what time is it")
    assert not _has_compound_or_followup_intent("take a screenshot")
    assert not _has_compound_or_followup_intent("close notepad")

    # Compound and messaging commands MUST be flagged as compound
    assert _has_compound_or_followup_intent("open whatsapp send hi message to dharmadurai k")
    assert _has_compound_or_followup_intent("open notepad and type hello world")
    assert _has_compound_or_followup_intent("open chrome then search for recipes")
    assert _has_compound_or_followup_intent("send hi message to dharmadurai k")
    assert _has_compound_or_followup_intent("text mom saying i will be late")


def test_router_classifies_messaging_as_multistep():
    from harma.core.router import classify_request, RequestTier

    tier, caps = classify_request("open whatsapp send hi message to dharmadurai k")
    assert tier == RequestTier.MULTI_STEP
    assert "open_application" in caps
    assert "focus_application" in caps
    assert "type_text" in caps
    assert "press_key" in caps
    assert "hotkey" in caps


def test_agent_does_not_fast_path_on_compound_messaging():
    """Verify agent does not exit prematurely after opening WhatsApp on compound request."""
    from harma.core.agent import HarmaAgent
    from harma.core.context import AgentContext
    from harma.llm.provider import LLMResponse, ToolCall

    ctx = AgentContext()

    # Mock LLM to return open_application on iteration 0, and then completion on iteration 1
    call_count = 0

    async def mock_complete(messages, tools=None, system=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_open",
                        name="open_application",
                        arguments={"application_name": "WhatsApp"},
                    )
                ],
                finish_reason="tool_calls",
            )
        else:
            return LLMResponse(
                content="I opened WhatsApp and sent 'hi' to dharmadurai k.",
                tool_calls=[],
                finish_reason="stop",
            )

    ctx.llm.complete = mock_complete
    agent = HarmaAgent(ctx, max_iterations=5)

    async def _run():
        with patch("os.startfile", create=True):
            return await agent.run("open whatsapp send hi message to dharmadurai k")

    resp = asyncio.run(_run())

    # Verify agent performed continuation (called LLM twice, did NOT abort on fast path)
    assert call_count == 2
    assert "sent" in resp.lower()
    assert "dharmadurai" in resp.lower()

