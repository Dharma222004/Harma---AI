"""
Harma Performance V2 Regression Test Suite

Enforces that future commits cannot silently regress on:
  1. Zero LLM calls on deterministic queries (fast-path)
  2. Bounded LLM iterations on single tools (completion gate)
  3. Strict tool set minimization (<= 20 tools on domain tasks vs 101)
  4. Tool schema caching
  5. LLM client & session reuse
  6. Context token budgeting
"""

from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch

from harma.config.settings import config
from harma.core.agent import HarmaAgent
from harma.core.context import AgentContext
from harma.core.execution_engine import ExecutionEngine
from harma.core.execution_state import ExecutionStatus, ReasoningBudget, TaskClassification
from harma.core.router import (
    RequestTier,
    ToolSchemaCache,
    classify_request,
    select_tools,
)
from harma.llm.factory import get_provider
from harma.llm.provider import (
    LLMProvider,
    LLMResponse,
    Message,
    ToolCall,
    ToolDefinition,
)
from harma.tools.base import BaseTool, PermissionLevel, ToolResult as BaseToolResult
from harma.tools.registry import ToolRegistry
from harma.tools.system.time_tools import GetCurrentTimeTool


class MockTestProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.call_count = 0

    @property
    def name(self) -> str:
        return "mock_test_provider"

    async def complete(self, messages, tools=None, system=None, **kwargs):
        self.call_count += 1
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(content="Done.", finish_reason="stop")

    async def stream(self, *args, **kwargs):
        resp = await self.complete(*args, **kwargs)
        yield resp.content

    async def health_check(self) -> bool:
        return True


class TestPerformanceV2Regressions(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register(GetCurrentTimeTool())

    async def test_deterministic_tool_fast_path_zero_llm(self):
        """Deterministic queries (time, sysinfo) must execute in < 200ms with ZERO LLM calls."""
        provider = MockTestProvider([])
        ctx = AgentContext(provider=provider, registry=self.registry)
        agent = HarmaAgent(ctx)

        t0 = time.perf_counter()
        resp = await agent.run("What time is it?")
        elapsed_ms = (time.perf_counter() - t0) * 1000

        self.assertIn("2026", resp)
        self.assertEqual(provider.call_count, 0, "Fast-path must make ZERO LLM calls")
        self.assertLess(elapsed_ms, 200.0, "Fast-path latency must be well under 200ms")
        meta = agent.last_execution_meta
        self.assertEqual(meta["status"], "completed")
        self.assertEqual(len(meta["tool_calls"]), 1)
        self.assertEqual(meta["tool_calls"][0]["tool"], "get_current_time")

    async def test_single_action_completion_gate_caps_at_one_llm_call(self):
        """Single tool requests must NOT enter a multi-iteration reasoning loop once verified."""
        class MockAppTool(BaseTool):
            name = "open_application"
            description = "Open an application"
            permission_level = PermissionLevel.SAFE
            parameters = {"type": "object", "properties": {"application_name": {"type": "string"}}}

            async def execute(self, **kwargs):
                return BaseToolResult(success=True, output="Opened Chrome.")

        self.registry.register(MockAppTool())

        provider = MockTestProvider([
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="c1", name="open_application", arguments={"application_name": "Chrome"})],
                finish_reason="tool_calls",
            ),
            # Second response should NEVER be called due to completion gate
            LLMResponse(content="Unexpected extra call", finish_reason="stop"),
        ])

        ctx = AgentContext(provider=provider, registry=self.registry)
        agent = HarmaAgent(ctx, max_iterations=5)

        with patch.object(ExecutionEngine, "verify_action", new_callable=AsyncMock) as mock_v:
            mock_v.return_value = (True, "Window 'Chrome' detected")
            resp = await agent.run("Open Chrome")

            self.assertIn("Chrome", resp)
            self.assertEqual(provider.call_count, 1, "Single verified action must complete after exactly 1 LLM call")
            self.assertEqual(agent.last_execution_meta["status"], "completed")

    def test_router_tool_minimization(self):
        """Router must narrow down 100+ tools to <= 20 domain tools for specific tasks."""
        all_defs = [
            ToolDefinition(name=f"random_tool_{i}", description="random", parameters={})
            for i in range(100)
        ]
        all_defs.extend([
            ToolDefinition(name="open_application", description="open", parameters={}),
            ToolDefinition(name="focus_application", description="focus", parameters={}),
            ToolDefinition(name="get_current_time", description="time", parameters={}),
            ToolDefinition(name="get_system_info", description="sys", parameters={}),
        ])

        # Desktop app query
        sel, tier, total = select_tools("open Chrome", all_defs)
        self.assertLessEqual(len(sel), 20, "Router must not expose more than 20 tools for app launches")
        self.assertTrue(any(t.name == "open_application" for t in sel))

        # Conversational query
        sel_c, tier_c, _ = select_tools("Hello Harma", all_defs)
        self.assertEqual(len(sel_c), 0, "Conversational queries must receive 0 tools")
        self.assertEqual(tier_c, RequestTier.TRIVIAL)

    def test_schema_cache_functionality(self):
        """ToolSchemaCache returns cached schema dict without rebuilding."""
        td = ToolDefinition(name="test_cached_tool", description="Test caching", parameters={"type": "object"})
        s1 = ToolSchemaCache.get_openai_schema(td)
        s2 = ToolSchemaCache.get_openai_schema(td)
        self.assertIs(s1, s2, "Subsequent schema calls must return the identical cached dictionary")

        ToolSchemaCache.invalidate("test_cached_tool")
        s3 = ToolSchemaCache.get_openai_schema(td)
        self.assertEqual(s1, s3)
        self.assertIsNot(s1, s3, "Invalidated schema must be cleanly regenerated")

    def test_provider_singleton_reuse(self):
        """get_provider reuses cached adapter instance across calls."""
        p1 = get_provider("nvidia")
        p2 = get_provider("nvidia")
        self.assertIs(p1, p2, "Provider factory must reuse singleton instance for connection pooling")

    def test_reasoning_budget_limits(self):
        """ReasoningBudget correctly budgets LLM calls based on task classification."""
        b_direct = ReasoningBudget.for_classification(TaskClassification.DIRECT_RESPONSE)
        self.assertEqual(b_direct.max_llm_calls, 1)

        b_determ = ReasoningBudget.for_classification(TaskClassification.DETERMINISTIC_TOOL)
        self.assertEqual(b_determ.max_llm_calls, 0)

        b_single = ReasoningBudget.for_classification(TaskClassification.SINGLE_TOOL)
        self.assertLessEqual(b_single.max_llm_calls, 2)

    def test_keyboard_normalize_keys_formats(self):
        """_normalize_keys correctly parses JSON strings, plus-delimited, and lists without typing raw punctuation."""
        from harma.computer.keyboard import _normalize_keys
        self.assertEqual(_normalize_keys('["ctrl", "t"]'), ["ctrl", "t"])
        self.assertEqual(_normalize_keys("['ctrl', 'c']"), ["ctrl", "c"])
        self.assertEqual(_normalize_keys("ctrl+t"), ["ctrl", "t"])
        self.assertEqual(_normalize_keys("ctrl + shift + esc"), ["ctrl", "shift", "esc"])
        self.assertEqual(_normalize_keys("ctrl, t"), ["ctrl", "t"])
        self.assertEqual(_normalize_keys(["ctrl", "t"]), ["ctrl", "t"])
        self.assertEqual(_normalize_keys('enter'), ["enter"])

    def test_browser_web_query_routes_to_browser_core(self):
        """Web browsing queries route to browser core capabilities instead of OS desktop app controls."""
        ctx = AgentContext()
        all_defs = ctx.registry.list_tool_definitions()
        prompt = "open edge and open bookmy show website and show what are the movies available in chennai location in tamil"
        selected, tier, _ = select_tools(prompt, all_defs)
        names = {t.name for t in selected}
        self.assertIn("navigate_to", names)
        self.assertIn("observe_page", names)
        self.assertIn("extract_page_text", names)
        self.assertNotIn("open_application", names)
        self.assertNotIn("hotkey", names)

    def test_browser_controller_auto_ensure_page(self):
        """BrowserController._ensure_page recovers when active_page is None instead of raising RuntimeError."""
        from harma.browser.controller import BrowserController
        from unittest.mock import MagicMock

        ctrl = BrowserController()
        mock_session = MagicMock()
        mock_session.is_open = True
        mock_session.active_page = None
        mock_session._context = MagicMock()
        mock_session.new_tab = AsyncMock(return_value=MagicMock())
        ctrl._session = mock_session

        async def run_check():
            page = await ctrl._ensure_page()
            self.assertIsNotNone(page)
            mock_session.new_tab.assert_awaited_once()

        asyncio.run(run_check())


if __name__ == "__main__":
    unittest.main()

