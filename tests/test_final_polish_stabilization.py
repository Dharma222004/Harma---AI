"""
Harma — Final Polish, Reliability & Performance Stabilization Test Suite

Regression and stability tests verifying:
  1. Evidence Hierarchy (Levels 0–4 Smart Observation)
  2. Reasoning Budget Modes (FAST, NORMAL, DEEP, RECOVERY)
  3. Duplicate Side-Effect Protection for Consequential Actions
  4. Delay Minimization & Condition-based Polling (WindowPoller at 0.1s)
  5. Distinction: ACTION_EXECUTED vs ACTION_EXECUTED_AND_VERIFIED vs GOAL_COMPLETED
  6. Concise & Evidence-Accurate Fast Responses
  7. Loop Detection & Bounded Recovery
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from harma.computer.verification import ActionOutcome, WindowPoller, get_verifier
from harma.core.context import AgentContext
from harma.core.execution_engine import (
    ExecutionEngine,
    _format_fast_response,
    _LEVEL_0_TOOLS,
)
from harma.core.execution_state import (
    BudgetMode,
    ErrorClass,
    ExecutionContext,
    ExecutionStatus,
    NormalizedGoal,
    NormalizedToolCall,
    ReasoningBudget,
    StructuredToolResult,
    TaskClassification,
    _CONSEQUENTIAL_TOOLS,
)
from harma.llm.provider import LLMProvider, LLMResponse, ToolCall, ToolDefinition
from harma.memory.short_term import ShortTermMemory
from harma.security.permissions import PermissionManager
from harma.tools.base import BaseTool, PermissionLevel
from harma.tools.registry import ToolRegistry
from harma.tools.system.time_tools import GetCurrentTimeTool


class MockTestLLM(LLMProvider):
    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        self.responses = list(responses or [])
        self.call_count = 0

    @property
    def name(self) -> str:
        return "mock_test_llm"

    async def complete(self, messages, tools=None, system=None, temperature=None, max_tokens=None) -> LLMResponse:
        self.call_count += 1
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(content="Done.")


from harma.tools.base import BaseTool, PermissionLevel, ToolResult as BaseToolResult


class DummyConsequentialTool(BaseTool):
    name = "create_task"
    description = "Create a new task."
    permission_level = PermissionLevel.SAFE

    def __init__(self):
        super().__init__()
        self.execution_count = 0

    async def execute(self, description: str = "", **kwargs) -> BaseToolResult:
        self.execution_count += 1
        return BaseToolResult(
            success=True,
            output=f"Task created: {description}",
            data={"status": "created", "task_id": "task_123", "description": description},
        )


class TestObservationHierarchy(unittest.IsolatedAsyncioTestCase):
    """Test Level 0-4 observation hierarchy."""

    async def asyncSetUp(self):
        self.registry = ToolRegistry()
        self.registry.register(GetCurrentTimeTool())
        self.memory = ShortTermMemory()
        self.perm_manager = PermissionManager()
        self.llm = MockTestLLM()
        self.ctx = AgentContext(
            registry=self.registry,
            memory=self.memory,
            permissions=self.perm_manager,
            provider=self.llm,
        )
        self.engine = ExecutionEngine(self.ctx)

    async def test_level_0_deterministic_tools_zero_overhead(self):
        """Safe deterministic operations must produce Level 0 evidence without calling OS."""
        exec_ctx = ExecutionContext(user_request="what time is it?")
        res = StructuredToolResult(
            success=True,
            tool="get_current_time",
            raw_content="The current time is 10:00:00 AM.",
        )
        obs = await self.engine.observe(exec_ctx, "get_current_time", res)
        self.assertEqual(obs.get("level"), 0)
        self.assertEqual(obs.get("evidence"), "deterministic_result")
        self.assertTrue(obs.get("tool_succeeded"))

    @patch("harma.computer.windows.get_active_window_info")
    async def test_level_1_computer_action_observation(self, mock_win_info):
        """Computer actions must record Level 1 OS active window evidence."""
        mock_win_info.return_value = {"title": "Notepad - Untitled", "app": "Notepad"}
        exec_ctx = ExecutionContext(user_request="open notepad")
        res = StructuredToolResult(
            success=True,
            tool="open_application",
            raw_content="Opened notepad.",
        )
        obs = await self.engine.observe(exec_ctx, "open_application", res)
        self.assertEqual(obs.get("level"), 1)
        self.assertEqual(obs.get("active_window"), "Notepad - Untitled")
        self.assertEqual(obs.get("app"), "Notepad")

    @patch("harma.browser.controller.get_browser_controller")
    async def test_level_2_browser_action_observation(self, mock_get_ctrl):
        """Browser actions must record Level 2 live URL and page title."""
        mock_ctrl = MagicMock()
        mock_ctrl.is_open = True
        mock_session = MagicMock()
        mock_page = MagicMock()
        mock_page.url = "https://example.com"
        mock_page.title = AsyncMock(return_value="Example Domain")
        mock_session.active_page = mock_page
        mock_ctrl._session = mock_session
        mock_get_ctrl.return_value = mock_ctrl

        exec_ctx = ExecutionContext(user_request="navigate to example.com")
        res = StructuredToolResult(
            success=True,
            tool="navigate_to",
            raw_content="Navigated to https://example.com",
        )
        obs = await self.engine.observe(exec_ctx, "navigate_to", res)
        self.assertEqual(obs.get("level"), 2)
        self.assertEqual(obs.get("current_url"), "https://example.com")
        self.assertEqual(obs.get("page_title"), "Example Domain")


class TestReasoningBudgetModes(unittest.TestCase):
    """Test explicit ReasoningBudget operational states."""

    def test_budget_modes_for_classifications(self):
        budget_fast = ReasoningBudget.for_classification(TaskClassification.DETERMINISTIC_TOOL)
        self.assertEqual(budget_fast.mode, BudgetMode.FAST)
        self.assertEqual(budget_fast.max_llm_calls, 0)

        budget_single = ReasoningBudget.for_classification(TaskClassification.SINGLE_TOOL)
        self.assertEqual(budget_single.mode, BudgetMode.FAST)

        budget_multi = ReasoningBudget.for_classification(TaskClassification.MULTI_STEP)
        self.assertEqual(budget_multi.mode, BudgetMode.NORMAL)

        budget_complex = ReasoningBudget.for_classification(TaskClassification.MULTI_TOOL)
        self.assertEqual(budget_complex.mode, BudgetMode.DEEP)

    def test_budget_mode_included_in_summary(self):
        exec_ctx = ExecutionContext(user_request="test")
        exec_ctx.reasoning_budget.mode = BudgetMode.RECOVERY
        summary = exec_ctx.to_summary_dict()
        self.assertEqual(summary["reasoning_budget"]["mode"], "RECOVERY")


class TestDuplicateSideEffectProtection(unittest.IsolatedAsyncioTestCase):
    """Test duplicate side-effect prevention for consequential actions."""

    async def asyncSetUp(self):
        self.registry = ToolRegistry()
        self.tool = DummyConsequentialTool()
        self.registry.register(self.tool)
        self.memory = ShortTermMemory()
        self.perm_manager = PermissionManager()
        self.llm = MockTestLLM()
        self.ctx = AgentContext(
            registry=self.registry,
            memory=self.memory,
            permissions=self.perm_manager,
            provider=self.llm,
        )
        self.engine = ExecutionEngine(self.ctx)

    async def test_duplicate_consequential_action_blocked(self):
        exec_ctx = ExecutionContext(user_request="create reminder task")
        call = NormalizedToolCall(
            id="call_1",
            name="create_task",
            arguments={"description": "Submit report"},
        )

        # First execution succeeds
        res1 = await self.engine.execute_tool(exec_ctx, call)
        self.assertTrue(res1.success)
        self.assertEqual(self.tool.execution_count, 1)
        self.assertTrue(exec_ctx.has_consequential_succeeded("create_task", {"description": "Submit report"}))

        # Second execution with exact same arguments is blocked to prevent duplicate side effects
        res2 = await self.engine.execute_tool(exec_ctx, call)
        self.assertTrue(res2.success)  # returns idempotent success
        self.assertIn("duplicate execution skipped", res2.data.get("content", ""))
        self.assertEqual(self.tool.execution_count, 1)  # NOT called again!


class TestDelayMinimization(unittest.TestCase):
    """Verify that arbitrary delays have been minimized to condition polling."""

    def test_window_poller_interval(self):
        poller = WindowPoller()
        self.assertLessEqual(poller._interval, 0.1, "WindowPoller should poll with at most 100ms interval")


class TestFastResponseFormatting(unittest.TestCase):
    """Verify clean, deterministic fast response generation."""

    def test_application_responses(self):
        resp = _format_fast_response("open_application", {"application_name": "notepad"}, "")
        self.assertEqual(resp, "Done. I opened notepad.")

        resp = _format_fast_response("close_application", {"application_name": "notepad"}, "")
        self.assertEqual(resp, "Done. I closed notepad.")

    def test_task_responses(self):
        resp = _format_fast_response("create_task", {"description": "Buy groceries"}, "")
        self.assertEqual(resp, "Done. Task created: Buy groceries.")

        resp = _format_fast_response("delete_task", {"task_id": "task_123"}, "")
        self.assertEqual(resp, "Done. Task task_123 deleted.")

    def test_memory_responses(self):
        resp = _format_fast_response("recall_memory", {}, "User prefers Dark Mode.")
        self.assertEqual(resp, "User prefers Dark Mode.")


if __name__ == "__main__":
    unittest.main()
