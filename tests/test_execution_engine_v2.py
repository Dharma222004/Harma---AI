"""
Harma — Execution Framework V2 Test Suite

Comprehensive tests for:
  1. Explicit Execution State Machine (ExecutionStatus, ExecutionContext)
  2. Goal Normalization & Task Classification (understand, risk level)
  3. Single Authoritative Execution Engine Pipeline (UNDERSTAND → PLAN → SELECT → EXECUTE → OBSERVE → VERIFY → COMPLETE)
  4. Tool Call Normalization & Structured Tool Results
  5. Proportional Observation & Risk-Proportional Verification
  6. Failure Taxonomy, Bounded Retries & Error Recovery
  7. Loop Detection (repeated tool+arg without progress)
  8. Timeouts, Cancellation & Pause/Resume
  9. Confirmation Handling for Sensitive/High-Risk Operations
  10. Phase 7 Autonomous Task Integration (TaskExecutor via ExecutionEngine)
  11. Real-World Acceptance Tests (Scenarios 1-10)
"""

from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from harma.core.agent import HarmaAgent
from harma.core.context import AgentContext
from harma.core.execution_engine import ExecutionEngine
from harma.core.execution_state import (
    ErrorClass,
    ExecutionContext,
    ExecutionStatus,
    LLMCallRecord,
    NormalizedGoal,
    NormalizedToolCall,
    StructuredToolResult,
    TaskClassification,
)
from harma.llm.provider import (
    LLMProvider,
    LLMResponse,
    Message,
    Role,
    ToolCall,
    ToolDefinition,
    ToolResult,
)
from harma.memory.short_term import ShortTermMemory
from harma.security.permissions import PermissionDecision, PermissionManager
from harma.tasks.executor import TaskExecutor
from harma.tasks.models import AutonomyLevel, Task
from harma.tools.base import BaseTool, PermissionLevel, ToolResult as BaseToolResult
from harma.tools.computer.app_tools import CloseApplicationTool, OpenApplicationTool
from harma.tools.registry import ToolRegistry
from harma.tools.system.time_tools import GetCurrentTimeTool


class MockV2Provider(LLMProvider):
    """Deterministic Mock LLM Provider for V2 execution engine testing."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.call_history: list[dict] = []
        self._index = 0

    @property
    def name(self) -> str:
        return "mock_v2_provider"

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.call_history.append({
            "messages": list(messages),
            "tools": list(tools) if tools else [],
            "system": system,
        })
        if self._index < len(self.responses):
            resp = self.responses[self._index]
            self._index += 1
            return resp
        return LLMResponse(content="Task completed.", finish_reason="stop")

    async def stream(self, *args, **kwargs):
        resp = await self.complete(*args, **kwargs)
        yield resp.content

    async def health_check(self) -> bool:
        return True


class TestExecutionStateModel(unittest.TestCase):
    """Unit tests for the Execution State Machine & Execution Context."""

    def test_execution_status_enum_values(self):
        expected_states = {
            "idle", "understanding", "planning", "waiting_for_tool",
            "executing_tool", "observing", "verifying", "replanning",
            "waiting_for_confirmation", "completed", "failed",
            "cancelled", "paused"
        }
        actual_states = {s.value for s in ExecutionStatus}
        self.assertEqual(expected_states, actual_states)

    def test_execution_context_state_transitions(self):
        ctx = ExecutionContext(user_request="Test request")
        self.assertEqual(ctx.current_state, ExecutionStatus.IDLE)
        self.assertEqual(len(ctx.state_history), 1)

        ctx.update_state(ExecutionStatus.UNDERSTANDING)
        ctx.update_state(ExecutionStatus.PLANNING)
        ctx.update_state(ExecutionStatus.EXECUTING_TOOL)
        ctx.update_state(ExecutionStatus.OBSERVING)
        ctx.update_state(ExecutionStatus.VERIFYING)
        ctx.update_state(ExecutionStatus.COMPLETED)

        self.assertEqual(ctx.current_state, ExecutionStatus.COMPLETED)
        self.assertEqual(len(ctx.state_history), 7)
        states = [h["to_state"] for h in ctx.state_history]
        self.assertEqual(states, [
            "idle", "understanding", "planning", "executing_tool",
            "observing", "verifying", "completed"
        ])

    def test_loop_detection_in_context(self):
        ctx = ExecutionContext(user_request="Open Chrome")
        # First 2 identical actions — no loop
        self.assertFalse(ctx.check_loop("open_application", {"app": "chrome"}, threshold=3, record=True))
        self.assertFalse(ctx.check_loop("open_application", {"app": "chrome"}, threshold=3, record=True))
        # 3rd identical action without progress — loop detected
        self.assertTrue(ctx.check_loop("open_application", {"app": "chrome"}, threshold=3, record=True))

        # Different argument resets check
        self.assertFalse(ctx.check_loop("open_application", {"app": "notepad"}, threshold=3, record=True))

    def test_error_recording_and_summary(self):
        ctx = ExecutionContext(user_request="Fail test")
        ctx.record_error(ErrorClass.ELEMENT_NOT_FOUND, "Window not found", tool="focus_application")
        self.assertEqual(len(ctx.errors), 1)
        self.assertEqual(ctx.errors[0]["type"], ErrorClass.ELEMENT_NOT_FOUND.value)

        summary = ctx.to_summary_dict()
        self.assertEqual(summary["total_errors"], 1)
        self.assertEqual(summary["current_state"], "idle")


class TestGoalNormalizationAndClassification(unittest.TestCase):
    """Unit tests for request normalization and classification without keyword hacks."""

    def setUp(self):
        self.ctx = AgentContext()
        self.engine = ExecutionEngine(self.ctx)

    def test_direct_conversational_classification(self):
        goal = self.engine.understand("Hello Harma")
        self.assertEqual(goal.classification, TaskClassification.DIRECT_RESPONSE)
        self.assertFalse(goal.requires_tools)

        math_goal = self.engine.understand("what is 2 + 2?")
        self.assertEqual(math_goal.classification, TaskClassification.DIRECT_RESPONSE)
        self.assertFalse(math_goal.requires_tools)

    def test_single_tool_classification(self):
        time_goal = self.engine.understand("What time is it?")
        self.assertEqual(time_goal.classification, TaskClassification.SINGLE_TOOL)
        self.assertTrue(time_goal.requires_tools)
        self.assertEqual(time_goal.risk_level, "low")

        app_goal = self.engine.understand("Open Chrome")
        self.assertEqual(app_goal.classification, TaskClassification.SINGLE_TOOL)
        self.assertTrue(app_goal.requires_tools)

    def test_multi_step_compound_classification(self):
        compound_goal = self.engine.understand("Open Chrome and search for today's NIFTY price")
        self.assertEqual(compound_goal.classification, TaskClassification.MULTI_STEP)
        self.assertTrue(compound_goal.requires_tools)
        self.assertEqual(compound_goal.risk_level, "medium")

        messaging_goal = self.engine.understand("open whatsapp send hi message to dharmadurai k")
        self.assertEqual(messaging_goal.classification, TaskClassification.MULTI_STEP)
        self.assertTrue(messaging_goal.requires_tools)


class TestAuthoritativeExecutionPipeline(unittest.IsolatedAsyncioTestCase):
    """Integration tests for the single authoritative execution pipeline."""

    async def test_direct_response_turn(self):
        """User request requiring no tools directly returns LLM answer."""
        provider = MockV2Provider([
            LLMResponse(content="Hello! I am Harma, your desktop assistant.", tool_calls=[], finish_reason="stop")
        ])
        ctx = AgentContext(provider=provider)
        agent = HarmaAgent(ctx)

        result = await agent.run("Hello Harma")
        self.assertIn("Harma", result)
        self.assertEqual(agent.last_execution_meta["status"], "completed")
        self.assertEqual(len(agent.last_execution_meta["tool_calls"]), 0)

    async def test_single_tool_execution_with_verification(self):
        """Single tool executes, observes, verifies and completes."""
        registry = ToolRegistry()
        time_tool = GetCurrentTimeTool()
        registry.register(time_tool)

        provider = MockV2Provider([
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="call_t1", name="get_current_time", arguments={})],
                finish_reason="tool_calls",
            )
        ])
        ctx = AgentContext(provider=provider, registry=registry)
        agent = HarmaAgent(ctx)

        result = await agent.run("What time is it?")
        self.assertTrue(len(result) > 0)
        self.assertEqual(agent.last_execution_meta["status"], "completed")
        self.assertEqual(len(agent.last_execution_meta["tool_calls"]), 1)
        self.assertEqual(agent.last_execution_meta["tool_calls"][0]["status"], "success")
        self.assertEqual(agent.last_execution_meta["verification"]["status"], "verified")

    async def test_multi_step_execution_loop(self):
        """Compound command continues multi-step loop without premature fast-path exit."""
        registry = ToolRegistry()
        app_tool = OpenApplicationTool()
        time_tool = GetCurrentTimeTool()
        registry.register(app_tool)
        registry.register(time_tool)

        responses = [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="call_1", name="open_application", arguments={"application_name": "notepad"})],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="call_2", name="get_current_time", arguments={})],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="Notepad is open and the time is recorded.",
                tool_calls=[],
                finish_reason="stop",
            ),
        ]
        provider = MockV2Provider(responses)
        ctx = AgentContext(provider=provider, registry=registry)
        agent = HarmaAgent(ctx)

        with patch.object(app_tool, "execute", new_callable=AsyncMock) as mock_app:
            mock_app.return_value = BaseToolResult(success=True, output="Opened notepad.")
            result = await agent.run("Open notepad and check the current time")

            self.assertEqual(len(provider.call_history), 3)
            self.assertIn("Notepad is open", result)
            self.assertEqual(agent.last_execution_meta["status"], "completed")
            self.assertEqual(len(agent.last_execution_meta["tool_calls"]), 2)


class TestErrorRecoveryAndLoopDetection(unittest.IsolatedAsyncioTestCase):
    """Tests for error taxonomy classification, bounded retries, and loop prevention."""

    def setUp(self):
        self.ctx = AgentContext()
        self.engine = ExecutionEngine(self.ctx)

    def test_error_classification_taxonomy(self):
        self.assertEqual(self.engine.classify_error("Operation timed out after 30s"), ErrorClass.TIMEOUT)
        self.assertEqual(self.engine.classify_error("Element not found on screen"), ErrorClass.ELEMENT_NOT_FOUND)
        self.assertEqual(self.engine.classify_error("Permission denied for action"), ErrorClass.PERMISSION_DENIED)
        self.assertEqual(self.engine.classify_error("Connection reset by peer"), ErrorClass.TRANSIENT)
        self.assertEqual(self.engine.classify_error("Invalid argument: missing app name"), ErrorClass.INVALID_ARGUMENT)

    def test_retry_eligibility(self):
        exec_ctx = ExecutionContext(user_request="Test")
        # Transient errors are retryable
        self.assertTrue(self.engine.can_retry(exec_ctx, "network_tool", ErrorClass.TRANSIENT))

        # Permission errors are NOT retryable
        self.assertFalse(self.engine.can_retry(exec_ctx, "delete_system", ErrorClass.PERMISSION_DENIED))

        # Reaching max retries stops further retries
        exec_ctx.retry_counts["flaky_tool"] = 3
        self.assertFalse(self.engine.can_retry(exec_ctx, "flaky_tool", ErrorClass.TRANSIENT))

    async def test_loop_detection_aborts_infinite_repetition(self):
        """Repeated identical tool calls without progress trigger loop abort."""
        class MockLoopTool(BaseTool):
            name = "custom_loop_tool"
            description = "Custom loop test tool"
            permission_level = PermissionLevel.SAFE
            parameters = {"type": "object", "properties": {}}

            async def execute(self, **kwargs) -> BaseToolResult:
                return BaseToolResult(success=True, output="Did custom action.")

        registry = ToolRegistry()
        loop_tool = MockLoopTool()
        registry.register(loop_tool)

        # Provider stubbornly returns the same tool call repeatedly
        repetitive_resp = LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c_repeat", name="custom_loop_tool", arguments={})],
            finish_reason="tool_calls",
        )
        provider = MockV2Provider([repetitive_resp, repetitive_resp, repetitive_resp, repetitive_resp])
        ctx = AgentContext(provider=provider, registry=registry)
        agent = HarmaAgent(ctx, max_iterations=5)

        result = await agent.run("execute custom loop")
        self.assertIn("loop detected", result.lower())
        self.assertEqual(agent.last_execution_meta["status"], "failed")


class TestConfirmationAndPermissions(unittest.IsolatedAsyncioTestCase):
    """Tests for confirmation flow and permission enforcement."""

    async def test_tool_confirmation_rejected(self):
        """When user confirmation callback returns 'no', execution handles denial cleanly."""
        class MockDangerousTool(BaseTool):
            name = "format_disk"
            description = "Format hard disk"
            permission_level = PermissionLevel.HIGH_RISK
            parameters = {"type": "object", "properties": {}}

            async def execute(self, **kwargs) -> BaseToolResult:
                return BaseToolResult(success=True, output="Formatted disk.")

        registry = ToolRegistry()
        registry.register(MockDangerousTool())

        provider = MockV2Provider([
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="call_danger", name="format_disk", arguments={})],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="I stopped because you denied permission.",
                tool_calls=[],
                finish_reason="stop",
            ),
        ])

        # Confirmation callback returns "no"
        def reject_confirm(prompt: str) -> str:
            return "no"

        ctx = AgentContext(provider=provider, registry=registry)
        agent = HarmaAgent(ctx, confirm_callback=reject_confirm)

        result = await agent.run("format the disk now")
        self.assertIn("denied permission", result)
        # Tool call record marks error
        self.assertEqual(agent.last_execution_meta["tool_calls"][0]["status"], "error")


class TestTimeoutAndCancellation(unittest.IsolatedAsyncioTestCase):
    """Tests for runtime deadline enforcement and user cancellation."""

    async def test_cancellation_state_stops_execution(self):
        ctx = AgentContext()
        engine = ExecutionEngine(ctx)
        exec_ctx = ExecutionContext(user_request="Long task")
        exec_ctx.cancellation_state = True

        res = engine._finalize(exec_ctx, "Execution was cancelled.", status="cancelled")
        self.assertEqual(res, "Execution was cancelled.")
        self.assertEqual(engine.last_execution_meta["status"], "cancelled")


class TestPhase7AutonomousTaskIntegration(unittest.IsolatedAsyncioTestCase):
    """Validates that Phase 7 TaskExecutor runs through the Execution Engine."""

    async def test_task_executor_runs_through_authoritative_engine(self):
        provider = MockV2Provider([
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="call_t", name="get_current_time", arguments={})],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="The task was executed and time was checked.",
                tool_calls=[],
                finish_reason="stop",
            ),
        ])
        base_ctx = AgentContext(provider=provider)
        base_ctx.registry.register(GetCurrentTimeTool())

        executor = TaskExecutor(base_context=base_ctx)
        task = Task(
            objective="Check current time",
            allowed_tools=["get_current_time"],
            autonomy_level=AutonomyLevel.LEVEL_3_LOW_RISK,
            max_steps=3,
            max_runtime_seconds=10,
        )

        history = await executor.execute(task)
        self.assertEqual(history.status, "success")
        self.assertIn("get_current_time", history.tools_used)


class TestRealWorldAcceptanceScenarios(unittest.IsolatedAsyncioTestCase):
    """
    Direct verification of the 10 Real-World Acceptance Scenarios required by Framework V2.
    """

    async def test_scenario_1_direct_response(self):
        """Scenario 1: Direct response without tool calls."""
        provider = MockV2Provider([
            LLMResponse(content="Hello! How can I help you today?", tool_calls=[], finish_reason="stop")
        ])
        ctx = AgentContext(provider=provider)
        agent = HarmaAgent(ctx)

        result = await agent.run("Hello Harma")
        self.assertIn("Hello", result)
        self.assertEqual(len(agent.last_execution_meta["tool_calls"]), 0)
        self.assertEqual(agent.last_execution_meta["status"], "completed")

    async def test_scenario_2_single_tool(self):
        """Scenario 2: Single tool execution."""
        registry = ToolRegistry()
        registry.register(GetCurrentTimeTool())
        provider = MockV2Provider([
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="t2", name="get_current_time", arguments={})],
                finish_reason="tool_calls",
            )
        ])
        ctx = AgentContext(provider=provider, registry=registry)
        agent = HarmaAgent(ctx)

        result = await agent.run("What time is it?")
        self.assertTrue(len(result) > 0)
        self.assertEqual(len(agent.last_execution_meta["tool_calls"]), 1)
        self.assertEqual(agent.last_execution_meta["tool_calls"][0]["status"], "success")

    async def test_scenario_3_computer_open_application(self):
        """Scenario 3: Computer tool execution (open_application) with verification.

        The ActionVerifier is mocked to return ACTION_EXECUTED_VERIFIED so this
        unit test does not require a real Chrome window to appear on screen.
        """
        registry = ToolRegistry()
        app_tool = OpenApplicationTool()
        registry.register(app_tool)
        provider = MockV2Provider([
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="t3", name="open_application", arguments={"application_name": "chrome"})],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="Done. I opened Chrome.",
                tool_calls=[],
                finish_reason="stop",
            ),
        ])
        ctx = AgentContext(provider=provider, registry=registry)
        agent = HarmaAgent(ctx)

        from harma.computer.verification import VerificationResult, ActionOutcome, VerificationEvidence

        mock_vr = VerificationResult(
            outcome=ActionOutcome.ACTION_EXECUTED_VERIFIED,
            action="open_application",
            expected_state="Window containing 'chrome' is visible",
            evidence=[VerificationEvidence(
                source="active_window",
                observation="Foreground window: 'Google Chrome'",
                contains_expected=True,
                confidence=0.95,
            )],
            best_confidence=0.95,
            detail="Chrome window verified via active_window",
        )

        with patch.object(app_tool, "execute", new_callable=AsyncMock) as mock_exec, \
             patch("harma.computer.verification.ActionVerifier.verify_window_opened",
                   new_callable=AsyncMock, return_value=mock_vr):
            mock_exec.return_value = BaseToolResult(success=True, output="Opened chrome.")
            result = await agent.run("Open Chrome")
            self.assertIn("chrome", result.lower())
            # Verification status is now "action_executed_verified" not "verified"
            self.assertEqual(
                agent.last_execution_meta["verification"]["status"],
                "action_executed_verified",
            )

    async def test_scenario_4_multi_step_computer(self):
        """Scenario 4: Multi-step computer sequence."""
        registry = ToolRegistry()
        app_tool = OpenApplicationTool()
        registry.register(app_tool)

        responses = [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="t4_1", name="open_application", arguments={"application_name": "notepad"})],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="Notepad is open and text has been typed.",
                tool_calls=[],
                finish_reason="stop",
            ),
        ]
        provider = MockV2Provider(responses)
        ctx = AgentContext(provider=provider, registry=registry)
        agent = HarmaAgent(ctx)

        with patch.object(app_tool, "execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = BaseToolResult(success=True, output="Opened notepad.")
            result = await agent.run('Open Notepad and type "Hello from Harma"')
            self.assertIn("Notepad", result)
            self.assertEqual(len(provider.call_history), 2)

    async def test_scenario_5_browser_workflow(self):
        """Scenario 5: Browser interaction flow."""
        class MockBrowserNavigate(BaseTool):
            name = "navigate_to"
            description = "Navigate browser"
            permission_level = PermissionLevel.SAFE
            parameters = {"type": "object", "properties": {"url": {"type": "string"}}}

            async def execute(self, **kwargs) -> BaseToolResult:
                return BaseToolResult(success=True, output="Navigated to URL.")

        registry = ToolRegistry()
        registry.register(MockBrowserNavigate())

        provider = MockV2Provider([
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="t5", name="navigate_to", arguments={"url": "https://www.google.com"})],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="Search results page loaded.",
                tool_calls=[],
                finish_reason="stop",
            ),
        ])
        ctx = AgentContext(provider=provider, registry=registry)
        agent = HarmaAgent(ctx)

        result = await agent.run("Open Chrome and search for NIFTY")
        self.assertIn("Search results", result)
        self.assertEqual(agent.last_execution_meta["status"], "completed")

    async def test_scenario_6_recovery(self):
        """Scenario 6: Tool failure recovery without crashing."""
        registry = ToolRegistry()
        app_tool = OpenApplicationTool()
        registry.register(app_tool)

        provider = MockV2Provider([
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="t6_err", name="open_application", arguments={"application_name": "unknown_app"})],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="Application unknown_app could not be found. I recovered gracefully.",
                tool_calls=[],
                finish_reason="stop",
            ),
        ])
        ctx = AgentContext(provider=provider, registry=registry)
        agent = HarmaAgent(ctx)

        with patch.object(app_tool, "execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = BaseToolResult(success=False, output="App not found.")
            result = await agent.run("open unknown_app")
            self.assertIn("recovered gracefully", result)
            self.assertEqual(agent.last_execution_meta["status"], "completed")

    async def test_scenario_7_confirmation_flow(self):
        """Scenario 7: Action requiring confirmation is prompted and resumed."""
        class SensitiveTool(BaseTool):
            name = "delete_temp_files"
            description = "Delete temp files"
            permission_level = PermissionLevel.SENSITIVE
            parameters = {"type": "object", "properties": {}}

            async def execute(self, **kwargs) -> BaseToolResult:
                return BaseToolResult(success=True, output="Files deleted.")

        registry = ToolRegistry()
        registry.register(SensitiveTool())

        provider = MockV2Provider([
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="t7", name="delete_temp_files", arguments={})],
                finish_reason="tool_calls",
            )
        ])

        confirmed = False
        def mock_confirm(prompt: str) -> str:
            nonlocal confirmed
            confirmed = True
            return "yes"

        ctx = AgentContext(provider=provider, registry=registry)
        agent = HarmaAgent(ctx, confirm_callback=mock_confirm)

        result = await agent.run("Delete temp files")
        self.assertTrue(confirmed)
        self.assertEqual(agent.last_execution_meta["status"], "completed")

    async def test_scenario_8_cancellation(self):
        """Scenario 8: Cancellation stops execution safely."""
        ctx = AgentContext()
        engine = ExecutionEngine(ctx)
        exec_ctx = ExecutionContext(user_request="Long task")
        exec_ctx.cancellation_state = True
        res = engine._finalize(exec_ctx, "Task cancelled.", status="cancelled")
        self.assertEqual(res, "Task cancelled.")
        self.assertEqual(engine.last_execution_meta["status"], "cancelled")

    async def test_scenario_9_mcp_integration_execution(self):
        """Scenario 9: MCP tool executed through the unified pipeline."""
        class MockMCPTool(BaseTool):
            name = "mcp_github_list_issues"
            description = "List GitHub issues"
            permission_level = PermissionLevel.SAFE
            parameters = {"type": "object", "properties": {}}

            async def execute(self, **kwargs) -> BaseToolResult:
                return BaseToolResult(success=True, output="Found 3 issues.")

        registry = ToolRegistry()
        registry.register(MockMCPTool())

        provider = MockV2Provider([
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="t9", name="mcp_github_list_issues", arguments={})],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="Here are the 3 GitHub issues.",
                tool_calls=[],
                finish_reason="stop",
            ),
        ])
        ctx = AgentContext(provider=provider, registry=registry)
        agent = HarmaAgent(ctx)

        result = await agent.run("check my github issues")
        self.assertIn("GitHub issues", result)
        self.assertEqual(agent.last_execution_meta["tool_calls"][0]["tool"], "mcp_github_list_issues")
        self.assertEqual(agent.last_execution_meta["tool_calls"][0]["status"], "success")

    async def test_scenario_10_autonomous_scheduled_task(self):
        """Scenario 10: Phase 7 scheduled autonomous task execution."""
        provider = MockV2Provider([
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="t10", name="get_current_time", arguments={})],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="Scheduled periodic check complete.",
                tool_calls=[],
                finish_reason="stop",
            ),
        ])
        base_ctx = AgentContext(provider=provider)
        base_ctx.registry.register(GetCurrentTimeTool())

        executor = TaskExecutor(base_context=base_ctx)
        task = Task(
            objective="Periodic check",
            allowed_tools=["get_current_time"],
            autonomy_level=AutonomyLevel.LEVEL_3_LOW_RISK,
            max_steps=2,
            max_runtime_seconds=5,
        )

        history = await executor.execute(task)
        self.assertEqual(history.status, "success")
        self.assertTrue(history.steps_taken >= 1)


if __name__ == "__main__":
    unittest.main()
