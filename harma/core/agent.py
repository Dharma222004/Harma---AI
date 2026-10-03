"""
Harma Agent — Core Agent Loop (Phase 10.5 — Performance Optimized)

This is the central brain of Harma.

The agent loop:

  USER REQUEST
       ↓
  FAST INTENT ROUTING (zero LLM cost)
       ↓
  SELECTIVE TOOL LOADING (only relevant tools → smaller prompt)
       ↓
  LLM (understand request → select tool)
       ↓
  TOOL EXECUTION
       ↓
  LIGHTWEIGHT VERIFICATION
       ↓
  FAST PATH: if single deterministic tool succeeded → respond immediately
  OR
  FULL PATH: continue agent loop for complex tasks

Key optimizations over previous version:
  1. Capability router selects 5-15 tools instead of 101 → fewer tokens to LLM.
  2. Fast path skips the final LLM call for deterministic single-tool successes.
  3. System prompt removes mandatory observe_screen after every action.
  4. Memory retrieval is skipped for trivial commands.
  5. Full latency instrumentation added to every stage.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, AsyncIterator, Callable, Optional

from harma.config.logging_config import get_logger
from harma.config.settings import config
from harma.core.context import AgentContext
from harma.core.executor import Executor
from harma.core.perf import RequestTrace, Stage, record_trace
from harma.core.prompt import HARMA_SYSTEM_PROMPT
from harma.core.router import RequestTier, select_tools
from harma.llm.provider import Message, Role, ToolResult

log = get_logger(__name__)

# Tools whose successful single-step result is definitively self-describing.
# For these, we skip the final LLM continuation and return a formatted response directly.
_FAST_PATH_TOOLS: frozenset[str] = frozenset({
    "open_application",
    "close_application",
    "get_current_time",
    "get_system_info",
    "take_screenshot",
    "get_screen_size",
    "focus_application",
    "hotkey",
    "press_key",
    "type_text",
    "mouse_move",
    "mouse_click",
    "mouse_double_click",
    "mouse_right_click",
    "mouse_scroll",
})

# Tools that need observation after execution (complex state changes)
_NEEDS_OBSERVATION: frozenset[str] = frozenset({
    "browser_click", "browser_type", "browser_select",
    "navigate_to", "search_web",
    "android.tap", "android.type", "android.launch_app",
})


def _fast_response(tool_name: str, tool_call_args: dict, content: str) -> str:
    """
    Generate a simple confirmation response for a deterministic tool result.
    Avoids an entire LLM round-trip for simple tool successes.

    Args:
        tool_name: The tool that was called.
        tool_call_args: The arguments passed to the tool call.
        content: The raw content/output from the tool result.
    """
    if tool_name == "open_application":
        app = tool_call_args.get("application_name", "")
        return f"Done. I opened {app}." if app else "Done."

    if tool_name == "close_application":
        app = tool_call_args.get("application_name", "")
        return f"Done. I closed {app}." if app else "Done."

    if tool_name == "get_current_time":
        return content if content else "I checked the time."

    if tool_name == "get_system_info":
        return content if content else "Here is your system information."

    if tool_name == "take_screenshot":
        return content if content else "Screenshot captured."

    if tool_name == "get_screen_size":
        return content if content else "Screen size retrieved."

    if tool_name == "focus_application":
        return content or "Application focused."

    if tool_name in ("type_text", "hotkey", "press_key"):
        return "Done."

    if tool_name in ("mouse_move", "mouse_click", "mouse_double_click", "mouse_right_click", "mouse_scroll"):
        return "Done."

    return content or "Done."


def _has_compound_or_followup_intent(user_input: str) -> bool:
    """
    Check if the user's message indicates multiple actions, compound commands,
    or follow-up tasks. If True, the agent must NOT prematurely exit via fast-path
    after the first step.
    """
    text = user_input.strip().lower()

    # Check for connective words indicating sequential or multiple tasks
    if re.search(r"\b(and\s+(then\s+)?|then\s+|after\s+(that|which)\s+|also\s+)\b", text):
        return True

    # Check for compound actions: open/launch/start/run + action verb
    action_verbs = r"\b(send|message|msg|text|dm|type|write|search|find|play|click|press|email|tell|say|post|check)\b"
    has_open = bool(re.search(r"\b(open|launch|start|run)\b", text))
    has_action = bool(re.search(action_verbs, text))
    if has_open and has_action:
        return True

    # Check for direct messaging / communication patterns
    if re.search(r"\b(send|text|message|dm|tell|write)\b.{1,50}\b(to|message|msg|hi|hello|saying)\b", text):
        return True

    return False


class HarmaAgent:
    """
    The core Harma agent — powered by Authoritative Execution Engine V2.

    Usage:
        ctx = AgentContext()
        agent = HarmaAgent(ctx)
        response = await agent.run("What time is it?")
        print(response)
    """

    def __init__(
        self,
        context: AgentContext,
        confirm_callback: Optional[Callable[[str], str]] = None,
        max_iterations: Optional[int] = None,
    ) -> None:
        self._ctx = context
        self._executor = Executor(context, confirm_callback)
        self._max_iterations = (
            max_iterations if max_iterations is not None else config.agent.max_iterations
        )
        self.last_execution_meta: dict[str, Any] = {}

        # Authoritative Execution Engine V2
        from harma.core.execution_engine import ExecutionEngine
        self._engine = ExecutionEngine(
            context=self._ctx,
            confirm_callback=confirm_callback,
            max_iterations=self._max_iterations,
            executor=self._executor,
        )

        # Harma Runtime V3 (opt-in via HARMA_RUNTIME=v3) — created lazily on first use
        self._runner: Any = None

    # ── Runtime selection ─────────────────────────────────────────────────────────────────

    @staticmethod
    def runtime_version() -> str:
        return str(getattr(config.agent, "runtime", "v2") or "v2").lower()

    def get_runner(self) -> Any:
        """Return the HarmaRunner (V3), creating it on first use."""
        if self._runner is None:
            from harma.core.v3.runner import HarmaRunner
            self._runner = HarmaRunner(
                self._ctx,
                # Same confirmation channel as the existing Executor (CLI / voice / API callbacks).
                confirm_callback=lambda prompt: self._executor._confirm(prompt),
                max_iterations=self._max_iterations,
            )
        return self._runner

    # ── Main entry point ──────────────────────────────────────────────────────

    async def run(self, user_input: str, request_id: Optional[str] = None) -> str:
        """
        Process a user request and return Harma's final response via the Execution Engine.

        Args:
            user_input: The user's text message.
            request_id: Optional correlation ID for tracing.

        Returns:
            Harma's response string.
        """
        low = user_input.strip().lower()
        is_plan_cmd = low.startswith(("/plan ", "plan:", "/dry-run", "dry-run:"))
        if self.runtime_version() == "v3" and not is_plan_cmd:
            from harma.core.v3.runner import RunnerSetupError
            runner = self.get_runner()
            try:
                response = await runner.run(user_input, request_id=request_id)
                self.last_execution_meta = runner.last_execution_meta
                return response
            except RunnerSetupError as exc:
                # Safe: no tool has executed yet, so falling back cannot duplicate side effects.
                log.warning("[AGENT] Runtime V3 setup failed (%s); falling back to Execution Engine V2", exc)

        response = await self._engine.run(user_input, request_id=request_id)
        self.last_execution_meta = self._engine.last_execution_meta
        return response

    # ── Phase 9 Structured Plan Execution ─────────────────────────────────────

    async def run_plan(self, goal: str, dry_run: bool = False) -> str:
        """
        Execute a goal using the Phase 9 structured planning and verification engine.
        """
        response = await self._engine.run_plan(goal=goal, dry_run=dry_run)
        self.last_execution_meta = self._engine.last_execution_meta
        return response

    def get_plan_status(self) -> str:
        """Return the current status of the active plan."""
        planner = getattr(self._ctx, "planner", None)
        if not planner:
            return "No active planner available."
        return planner.state.status_summary()

    def pause_plan(self) -> None:
        """Pause active plan execution."""
        planner = getattr(self._ctx, "planner", None)
        if planner:
            planner.pause()

    def resume_plan(self) -> None:
        """Resume paused plan execution."""
        planner = getattr(self._ctx, "planner", None)
        if planner:
            planner.resume()

    def cancel_plan(self) -> None:
        """Cancel active plan execution."""
        planner = getattr(self._ctx, "planner", None)
        if planner:
            planner.cancel()

    def cancel(self, run_id: Optional[str] = None) -> list[str]:
        """Cancel active execution across Runner (V3), Engine (V2), and Planner."""
        cancelled: list[str] = []
        if self._runner is not None and hasattr(self._runner, "cancel"):
            cancelled.extend(self._runner.cancel(run_id))
        self.cancel_plan()
        return cancelled

    # ── Streaming variant ─────────────────────────────────────────────────────

    async def run_stream(self, user_input: str) -> AsyncIterator[str]:
        """
        Stream Harma's response token by token.
        """
        final = await self.run(user_input)
        yield final

    # ── Utility ───────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Clear session memory. Useful between unrelated conversations."""
        self._ctx.memory.clear()
        log.info("Agent session reset.")

    def status(self) -> str:
        """Return a human-readable status summary."""
        model_name = getattr(self._ctx.llm, "model", getattr(config.llm, "model", ""))
        lines = [
            "Harma LLM",
            f"Provider : {self._ctx.llm.name}",
            f"Model    : {model_name}",
            "Status   : Connected",
            "────────────────────",
            "Harma Agent",
            self._ctx.registry.summary(),
            self._ctx.memory.summary(),
        ]
        ltm = getattr(self._ctx, "long_term_memory", None)
        if ltm and hasattr(ltm, "summary"):
            lines.append(ltm.summary())
        return "\n".join(lines)

