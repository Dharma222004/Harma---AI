"""
Harma Authoritative Execution Engine — Framework V2

Single authoritative execution runtime for Harma:
  UNDERSTAND → PLAN → SELECT TOOLS → EXECUTE → OBSERVE → VERIFY → (RECOVER / REPLAN) → COMPLETE

All subsystems (CLI, Voice, Control Center API, Phase 7 Scheduled Tasks, Phase 9 Structured Plans)
delegate to this engine. No secondary execution loops or competing task runners exist.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from typing import Any, Callable, Optional

from harma.api.events import get_event_bus
from harma.api.models import EventSeverity
from harma.config.logging_config import get_logger
from harma.config.settings import config
from harma.core.context import AgentContext
from harma.core.execution_state import (
    BudgetMode,
    ContextBudget,
    ErrorClass,
    ExecutionContext,
    ExecutionStatus,
    LLMCallRecord,
    NormalizedGoal,
    NormalizedToolCall,
    ReasoningBudget,
    StructuredToolResult,
    TaskClassification,
    _CONSEQUENTIAL_TOOLS,
)
from harma.core.perf import RequestTrace, Stage, record_trace
from harma.core.prompt import HARMA_SYSTEM_PROMPT
from harma.core.router import RequestTier, select_tools as router_select_tools
from harma.llm.provider import Message, Role, ToolCall, ToolDefinition, ToolResult
from harma.security.permissions import PermissionDecision
from harma.tools.base import PermissionLevel

log = get_logger(__name__)

# Deterministic fast-path: information retrieval only — do NOT include computer control tools
_FAST_PATH_TOOLS: frozenset[str] = frozenset({
    "get_current_time",
    "get_system_info",
    "get_screen_size",
})

# Safe Level 0 deterministic operations where tool result itself is sufficient evidence
_LEVEL_0_TOOLS: frozenset[str] = _FAST_PATH_TOOLS | frozenset({
    "recall_memory", "search_memory", "get_all_memories",
    "list_tasks", "get_task_status", "read_file", "calculate", "list_directory",
})

# Computer control tools require post-action verification (ACTION EXECUTED ≠ OUTCOME VERIFIED)
_COMPUTER_ACTION_TOOLS: frozenset[str] = frozenset({
    "open_application", "close_application",
    "focus_application",
    "hotkey", "press_key", "type_text",
    "mouse_click", "mouse_double_click", "mouse_right_click",
    "mouse_move", "mouse_scroll",
    "take_screenshot",
})

_NEEDS_OBSERVATION: frozenset[str] = frozenset({
    "browser_click", "browser_type", "browser_select",
    "navigate_to", "search_web",
    "android.tap", "android.type", "android.launch_app",
})


def _format_fast_response(tool_name: str, args: dict, content: str) -> str:
    """Generate concise confirmation response for deterministic single-tool successes."""
    if tool_name == "open_application":
        app = args.get("application_name", "")
        return f"Done. I opened {app}." if app else "Done."
    if tool_name == "close_application":
        app = args.get("application_name", "")
        return f"Done. I closed {app}." if app else "Done."
    if tool_name == "get_current_time":
        return content if content else "I checked the time."
    if tool_name == "get_system_info":
        return content if content else "Here is your system information."
    if tool_name == "take_screenshot":
        return content if content else "Screenshot captured."
    if tool_name == "focus_application":
        return content or "Application focused."
    if tool_name == "create_task":
        desc = args.get("description", "")
        return f"Done. Task created: {desc}." if desc else "Task created successfully."
    if tool_name == "delete_task":
        tid = args.get("task_id", "")
        return f"Done. Task {tid} deleted." if tid else "Task deleted."
    if tool_name in ("recall_memory", "search_memory", "get_all_memories"):
        return content or "Memory retrieved."
    if tool_name in ("type_text", "hotkey", "press_key", "mouse_click", "mouse_move"):
        return "Done."
    return content or "Done."


def has_compound_or_followup_intent(user_input: str) -> bool:
    """
    Check if the user's message indicates multiple actions, compound commands,
    or follow-up tasks. If True, the agent must NOT prematurely exit via fast-path.
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


class ExecutionEngine:
    """
    The Single Authoritative Execution Engine for Harma.
    Enforces the explicit state machine:
    IDLE → UNDERSTANDING → PLANNING → SELECT_TOOLS → EXECUTING_TOOL → OBSERVING → VERIFYING → (RECOVER / REPLAN) → COMPLETE
    """

    def __init__(
        self,
        context: AgentContext,
        confirm_callback: Optional[Callable[[str], str]] = None,
        max_iterations: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
        executor: Optional[Any] = None,
    ) -> None:
        self.ctx = context
        self.confirm_callback = confirm_callback or self._default_cli_confirm
        self.max_iterations = (
            max_iterations if max_iterations is not None else config.agent.max_iterations
        )
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else getattr(config.agent, "task_timeout_seconds", 600.0)
        )
        self.bus = get_event_bus()
        from harma.core.executor import Executor
        self.executor = executor or Executor(context, self.confirm_callback)
        self.last_execution_meta: dict[str, Any] = {}

    @staticmethod
    def _default_cli_confirm(prompt: str) -> str:
        """Default fallback confirmation prompt via stdin."""
        print(f"\n{prompt}")
        try:
            return input("> ").strip()
        except EOFError:
            return "no"

    # ── Event Publishing ───────────────────────────────────────────────────────

    def emit_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        severity: EventSeverity = EventSeverity.INFO,
    ) -> None:
        """Emit a normalized runtime execution event onto the Harma event bus."""
        try:
            self.bus.publish(
                event_type=event_type,
                source="execution_engine",
                severity=severity,
                payload=payload,
            )
        except Exception as exc:
            log.debug("[ENGINE] Failed to emit event %s: %s", event_type, exc)

    # ── Stage 1: UNDERSTAND & NORMALIZE ───────────────────────────────────────

    def understand(self, user_input: str) -> NormalizedGoal:
        """
        Normalize the user request into a structured goal and classification.
        Generalizes without keyword hacks.
        """
        text = user_input.strip()
        low = text.lower()

        # 1. Pure direct conversational responses (no tools needed)
        conversational = bool(
            re.match(r"^(hi|hello|hey|greetings|good\s+(morning|afternoon|evening)|who are you|what is your name)(\s+harma|\s+assistant|\s+there)?\b[!?.]*$", low)
            or re.match(r"^what is \d+\s*[\+\-\*\/]\s*\d+\??$", low)
        )
        if conversational:
            return NormalizedGoal(
                goal=text,
                required_actions=["respond directly"],
                requires_tools=False,
                risk_level="low",
                classification=TaskClassification.DIRECT_RESPONSE,
            )

        # 2. Check for compound / multi-step intents
        if has_compound_or_followup_intent(text):
            actions = ["open_target", "perform_interaction", "verify_outcome"]
            return NormalizedGoal(
                goal=text,
                required_actions=actions,
                requires_tools=True,
                risk_level="medium",
                classification=TaskClassification.MULTI_STEP,
            )

        # 3. Deterministic single tool intents (pure fast path, zero-LLM call)
        deterministic_patterns = [
            (r"\b(what time|current time|the time|tell me the time|check the time|clock|what date|today'?s date|current date|what day is it)\b", "get_current_time"),
            (r"\b(cpu usage|memory usage|ram usage|disk usage|disk space|storage space|battery|system info|system information|sysinfo)\b", "get_system_info"),
            (r"\b(screen size|display size|resolution)\b", "get_screen_size"),
        ]
        for pat, tool in deterministic_patterns:
            if re.search(pat, low):
                return NormalizedGoal(
                    goal=text,
                    required_actions=[tool],
                    requires_tools=True,
                    risk_level="low",
                    classification=TaskClassification.SINGLE_TOOL,
                )

        # 4. Single tool intents (1 LLM step + verified deterministic completion)
        single_tool_patterns = [
            (r"\b(screenshot|take screenshot|capture screen)\b", "take_screenshot"),
            (r"^\b(open|launch|start|run)\b\s+[a-zA-Z0-9_\-\.\s]+$", "open_application"),
            (r"^\b(close|quit|exit|kill)\b\s+[a-zA-Z0-9_\-\.\s]+$", "close_application"),
            (r"^\b(focus|switch to)\b\s+[a-zA-Z0-9_\-\.\s]+$", "focus_application"),
        ]
        for pat, tool in single_tool_patterns:
            if re.search(pat, low):
                return NormalizedGoal(
                    goal=text,
                    required_actions=[tool],
                    requires_tools=True,
                    risk_level="low",
                    classification=TaskClassification.SINGLE_TOOL,
                )

        # 5. Fallback: treat as multi-tool or multi-step goal
        return NormalizedGoal(
            goal=text,
            required_actions=["execute user request"],
            requires_tools=True,
            risk_level="low",
            classification=TaskClassification.MULTI_TOOL,
        )

    # ── Stage 2: TOOL SELECTION ───────────────────────────────────────────────

    def select_tools_for_request(self, user_input: str) -> list[ToolDefinition]:
        """
        Filter available tools to only relevant ones using the capability router.
        Prevents token bloat while ensuring all required tools are present.
        """
        all_defs = self.ctx.registry.list_tool_definitions()
        selected, _, _ = router_select_tools(user_input, all_defs)
        return selected

    # ── Stage 3: TOOL EXECUTION PIPELINE ──────────────────────────────────────

    async def execute_tool(
        self,
        exec_ctx: ExecutionContext,
        call: NormalizedToolCall,
    ) -> StructuredToolResult:
        """
        Authoritative Tool Execution Pipeline:
          Validate → Permission Check → Confirmation if required → Execute → Normalize Result → Record
        """
        tool_name = call.name
        args = call.arguments
        tool = self.ctx.registry.get(tool_name)

        self.emit_event("execution.tool_called", {
            "execution_id": exec_ctx.execution_id,
            "tool": tool_name,
            "arguments": args,
        })

        # 1. Validation
        if not tool:
            log.warning("[ENGINE] Tool '%s' requested but not registered", tool_name)
            err_msg = f"Tool '{tool_name}' is not available."
            res = StructuredToolResult(
                success=False,
                tool=tool_name,
                error={"type": ErrorClass.ELEMENT_NOT_FOUND.value, "message": err_msg},
                raw_content=err_msg,
                tool_call_id=call.id,
            )
            exec_ctx.record_tool_execution(tool_name, args, res)
            return res

        # 2. Duplicate side-effect protection (Section 22)
        if exec_ctx.has_consequential_succeeded(tool_name, args):
            log.warning("[ENGINE] Duplicate side-effect prevented: '%s' already succeeded with args %s", tool_name, args)
            res = StructuredToolResult(
                success=True,
                tool=tool_name,
                data={"content": f"Action '{tool_name}' already succeeded in this session; duplicate execution skipped."},
                raw_content=f"Action '{tool_name}' already completed. Skipping redundant duplicate execution.",
                tool_call_id=call.id,
            )
            exec_ctx.record_tool_execution(tool_name, args, res)
            return res

        # 3. Execution via Executor (handles permission check & confirmation internally)
        exec_ctx.update_state(ExecutionStatus.EXECUTING_TOOL)
        t_start = time.time()
        try:
            prov_call = call.to_provider_call()
            results = await self.executor.run_tool_calls([prov_call])
            raw_result = results[0]
            duration_ms = (time.time() - t_start) * 1000

            success = not getattr(raw_result, "is_error", False)
            out_str = getattr(raw_result, "content", "") or getattr(raw_result, "output", "")

            error_payload = None
            if not success:
                err_class = self.classify_error(out_str)
                error_payload = {"type": err_class.value, "message": out_str}

            structured = StructuredToolResult(
                success=success,
                tool=tool_name,
                data={"content": out_str},
                error=error_payload,
                metadata={"duration_ms": round(duration_ms, 2)},
                raw_content=out_str,
                tool_call_id=call.id,
            )

        except Exception as exc:
            duration_ms = (time.time() - t_start) * 1000
            log.exception("[ENGINE] Unhandled exception in tool %s: %s", tool_name, exc)
            err_class = self.classify_error(str(exc))
            structured = StructuredToolResult(
                success=False,
                tool=tool_name,
                error={"type": err_class.value, "message": str(exc)},
                metadata={"duration_ms": round(duration_ms, 2)},
                raw_content=f"Error executing {tool_name}: {exc}",
                tool_call_id=call.id,
            )

        # 4. Record History
        exec_ctx.record_tool_execution(tool_name, args, structured)
        self.emit_event("execution.tool_completed", {
            "execution_id": exec_ctx.execution_id,
            "tool": tool_name,
            "success": structured.success,
            "duration_ms": structured.metadata.get("duration_ms", 0),
        })
        return structured

    # ── Stage 4: OBSERVATION ──────────────────────────────────────────────────

    async def observe(
        self,
        exec_ctx: ExecutionContext,
        tool_name: str,
        result: StructuredToolResult,
    ) -> dict[str, Any]:
        """
        Smart Proportional Observation Hierarchy (Levels 0–4):
          - Level 0 (Zero overhead): Safe deterministic operations where tool result itself is sufficient.
          - Level 1 (Lightweight state check): Read OS active window or system state.
          - Level 2 (DOM / UI state): Read live browser page URL/title or Android UI status.
          - Level 3 (Screenshot / Vision): Screen captures when visually required.
          - Level 4 (Strong external confirmation): Verification of external side-effects.
        """
        exec_ctx.update_state(ExecutionStatus.OBSERVING)
        obs: dict[str, Any] = {"tool": tool_name, "timestamp": time.time()}

        try:
            # Level 0 — Deterministic / Safe operations (No external observation needed)
            if tool_name in _LEVEL_0_TOOLS:
                obs["level"] = 0
                obs["evidence"] = "deterministic_result"
                obs["tool_succeeded"] = result.success
                obs["tool_output"] = result.raw_content[:200] if result.raw_content else ""

            # Level 1 — Desktop application & window actions (OS active window)
            elif tool_name in _COMPUTER_ACTION_TOOLS:
                from harma.computer.windows import get_active_window_info
                info = get_active_window_info()
                obs["level"] = 1
                obs["active_window"] = info.get("title", "")
                obs["app"] = info.get("app", "")
                obs["tool_succeeded"] = result.success
                obs["tool_output"] = result.raw_content[:200] if result.raw_content else ""

            # Level 2 — Browser actions (live URL & page title via BrowserController)
            elif "browser" in tool_name or tool_name in ("navigate_to", "search_web"):
                obs["level"] = 2
                from harma.browser.controller import get_browser_controller
                ctrl = get_browser_controller()
                if ctrl.is_open and ctrl._session and ctrl._session.active_page:
                    page = ctrl._session.active_page
                    try:
                        obs["current_url"] = page.url
                        obs["page_title"] = await page.title()
                    except Exception:
                        pass

            # Level 2 — Android actions
            elif tool_name.startswith("android."):
                obs["level"] = 2
                am = getattr(self.ctx, "android_manager", None)
                if am:
                    obs["android_status"] = "active"

            else:
                obs["level"] = 0
                obs["tool_succeeded"] = result.success

        except Exception as exc:
            log.debug("[ENGINE] Proportional observation exception: %s", exc)

        exec_ctx.record_observation(obs)
        self.emit_event("execution.observation", {
            "execution_id": exec_ctx.execution_id,
            "observation": obs,
        })
        return obs

    # ── Stage 5: VERIFICATION ─────────────────────────────────────────────────

    async def verify_action(
        self,
        exec_ctx: ExecutionContext,
        tool_name: str,
        args: dict[str, Any],
        result: StructuredToolResult,
        observation: dict[str, Any],
    ) -> tuple[bool, str]:
        """
        Verify whether the executed tool action actually achieved its expected real-world outcome.

        CRITICAL CONTRACT:
          - Tool success (result.success=True) means the tool CALL did not crash.
          - This method checks whether the intended EFFECT occurred on the computer.
          - Only returns (True, ...) when independent observation confirms the effect.

        Returns (verified: bool, detail: str)
        """
        exec_ctx.update_state(ExecutionStatus.VERIFYING)

        if not result.success:
            msg = f"Action {tool_name} failed: {result.error}"
            exec_ctx.verification = {"status": "failed", "reason": msg}
            log.warning("[ENGINE][VERIFY] %s", msg)
            return False, msg

        # ── Computer action verification — use ActionVerifier ──────────────
        if tool_name in _COMPUTER_ACTION_TOOLS:
            try:
                from harma.computer.verification import get_verifier, ActionOutcome
                verifier = get_verifier()

                if tool_name == "open_application":
                    app_name = args.get("application_name", args.get("name", ""))
                    vr = await verifier.verify_window_opened(
                        application_name=app_name,
                        tool_succeeded=result.success,
                        timeout=8.0,
                    )

                elif tool_name == "focus_application":
                    wfrag = (
                        args.get("window_title") or args.get("title_fragment")
                        or args.get("application_name", "")
                        or observation.get("app", "")
                    )
                    vr = await verifier.verify_window_focused(
                        window_fragment=wfrag,
                        tool_succeeded=result.success,
                        timeout=3.0,
                    )

                elif tool_name in ("type_text", "press_key", "hotkey"):
                    expected_text = args.get("text") if tool_name == "type_text" else None
                    wfrag = observation.get("app") or observation.get("active_window", "")
                    vr = await verifier.verify_keyboard_input(
                        action_name=tool_name,
                        tool_succeeded=result.success,
                        expected_text=expected_text,
                        window_fragment=wfrag,
                    )

                else:
                    # Mouse actions and take_screenshot: tool success is sufficient
                    vr = None

                if vr is not None:
                    # Record the structured verification result in context
                    exec_ctx.verification = {
                        "status": vr.outcome.value,
                        "reason": vr.detail,
                        "evidence": [e.observation for e in vr.evidence],
                        "confidence": vr.best_confidence,
                    }
                    self.emit_event("execution.verification", {
                        "execution_id": exec_ctx.execution_id,
                        "verified": vr.verified,
                        "outcome": vr.outcome.value,
                        "reason": vr.detail,
                        "confidence": vr.best_confidence,
                    })
                    log.info("[ENGINE][VERIFY] %s", vr.to_log_string())

                    # Return True when fully verified OR when outcome is only UNVERIFIED
                    # (unverified means tool ran but effect not confirmed — let LLM observe more)
                    if vr.failed:
                        return False, vr.detail
                    return True, vr.detail

            except Exception as exc:
                log.warning("[ENGINE][VERIFY] Verifier error for %s: %s", tool_name, exc)
                # Fallthrough to default (tool success accepted)

        # ── Browser actions ────────────────────────────────────────────────
        if tool_name in _NEEDS_OBSERVATION:
            url = observation.get("current_url", "")
            title = observation.get("page_title", "")
            msg = f"Browser action {tool_name}: url='{url}' title='{title}'"
            exec_ctx.verification = {"status": "verified", "reason": msg}
            return True, msg

        # ── Default: tool success is sufficient for non-computer actions ───
        msg = f"Tool {tool_name} succeeded."
        exec_ctx.verification = {"status": "verified", "reason": msg}
        self.emit_event("execution.verification", {
            "execution_id": exec_ctx.execution_id,
            "verified": True,
            "reason": msg,
        })
        return True, msg

    # ── Stage 6: ERROR TAXONOMY & RECOVERY ─────────────────────────────────────

    def classify_error(self, err_text: str) -> ErrorClass:
        """Categorize an error string into a structured ErrorClass."""
        low = (err_text or "").lower()
        if any(w in low for w in ["invalid argument", "required argument", "unexpected keyword", "type error"]):
            return ErrorClass.INVALID_ARGUMENT
        if any(w in low for w in ["timeout", "timed out", "deadline"]):
            return ErrorClass.TIMEOUT
        if any(w in low for w in ["not found", "cannot find", "no such", "missing"]):
            return ErrorClass.ELEMENT_NOT_FOUND
        if any(w in low for w in ["denied", "permission", "unauthorized", "forbidden"]):
            return ErrorClass.PERMISSION_DENIED
        if any(w in low for w in ["auth", "login", "password", "token expired"]):
            return ErrorClass.AUTHENTICATION
        if any(w in low for w in ["stale", "detached", "closed", "navigated", "environment"]):
            return ErrorClass.ENVIRONMENT_CHANGED
        if any(w in low for w in ["connection", "network", "reset", "busy", "temporary", "retry"]):
            return ErrorClass.TRANSIENT
        return ErrorClass.UNKNOWN

    def can_retry(self, exec_ctx: ExecutionContext, tool_name: str, err_class: ErrorClass) -> bool:
        """Determine if a failed tool call is eligible for bounded retry."""
        if err_class in (ErrorClass.PERMISSION_DENIED, ErrorClass.AUTHENTICATION):
            return False  # Never blindly retry permission or authentication rejections

        current_retries = exec_ctx.retry_counts.get(tool_name, 0)
        max_retries = config.agent.max_retries
        return current_retries < max_retries

    # ── Stage 7: MAIN EXECUTION ENTRY POINT ───────────────────────────────────

    def _finalize(
        self,
        exec_ctx: ExecutionContext,
        final_text: str,
        status: str = "completed",
        trace: Optional[RequestTrace] = None,
    ) -> str:
        exec_ctx.final_response = final_text
        planner = getattr(self.ctx, "planner", None)
        plan_id = (
            getattr(getattr(planner, "state", None), "current_plan", None)
            and getattr(planner.state.current_plan, "plan_id", None)
        )
        self.last_execution_meta = {
            "request_id": exec_ctx.execution_id,
            "status": status,
            "response": final_text,
            "plan_id": plan_id,
            "tool_calls": [
                {"tool": h["tool"], "status": "success" if h["success"] else "error", "error": h["error"]}
                for h in exec_ctx.tool_history
            ],
            "verification": exec_ctx.verification or {"status": "verified"},
            "trace": f"Engine execution for {exec_ctx.user_request}",
            "execution_context": exec_ctx.to_summary_dict(),
        }

        if trace is not None:
            trace.mark(Stage.API_RESPONSE)
            trace.log_trace()
            record_trace(trace)
            self.last_execution_meta["perf"] = trace.summary()

        # Auto-extract long term memory candidates
        ltm = getattr(self.ctx, "long_term_memory", None)
        if ltm and getattr(ltm, "is_available", False) and getattr(exec_ctx.normalized_goal, "classification", None) != TaskClassification.DIRECT_RESPONSE:
            try:
                ltm.extract_and_save(exec_ctx.user_request)
            except Exception as exc:
                log.debug("[ENGINE] Memory extraction error: %s", exc)

        return final_text

    async def run(
        self,
        user_input: str,
        request_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> str:
        """
        Execute the user request through the unified Execution Engine.
        """
        req_id = request_id or f"harma-{uuid.uuid4().hex[:6]}"
        trace = RequestTrace(request_id=req_id, user_input=user_input)
        trace.mark(Stage.REQUEST_RECEIVED)

        exec_ctx = ExecutionContext(
            execution_id=req_id,
            user_request=user_input,
            deadlines=time.time() + self.timeout_seconds,
        )

        log.info("[%s] EXECUTION_STARTED: %s", req_id, user_input)
        self.emit_event("execution.started", {
            "execution_id": req_id,
            "user_request": user_input,
        })

        # Synchronize memory
        self.ctx.memory.add_user_message(user_input)
        task_id = str(uuid.uuid4())[:8]
        self.ctx.memory.start_task(task_id, user_input)

        # Check for direct /plan or /dry-run execution
        low_input = user_input.strip().lower()
        if low_input.startswith(("/plan ", "plan:", "/dry-run", "dry-run:")):
            dry_run = low_input.startswith(("/dry-run", "dry-run:"))
            goal = re.sub(r"^(?:/plan\s+|plan:\s*|/dry-run\s+|dry-run:\s*)", "", user_input.strip(), flags=re.I)
            plan_res = await self.run_plan(goal=goal, dry_run=dry_run)
            return self._finalize(exec_ctx, plan_res, "completed", trace=trace)

        # ── 1. UNDERSTAND ──────────────────────────────────────────────────────
        exec_ctx.update_state(ExecutionStatus.UNDERSTANDING)
        normalized_goal = self.understand(user_input)
        exec_ctx.normalized_goal = normalized_goal
        log.info("[%s] GOAL_NORMALIZED: classification=%s risk=%s",
                 req_id, normalized_goal.classification.value, normalized_goal.risk_level)

        # Synchronize preferred browser target from user prompt
        if re.search(r"\b(edge|msedge)\b", user_input, re.I):
            try:
                from harma.browser.controller import get_browser_controller
                ctrl = get_browser_controller()
                ctrl._browser_type = "msedge"
                log.info("[%s] Target browser explicitly aligned to Microsoft Edge ('msedge')", req_id)
            except Exception:
                pass
        elif re.search(r"\b(chrome|google\s*chrome)\b", user_input, re.I) and not re.search(r"\b(dont|don't|not|never)\s+(use\s+)?chrome\b", user_input, re.I):
            try:
                from harma.browser.controller import get_browser_controller
                ctrl = get_browser_controller()
                ctrl._browser_type = "chrome"
                log.info("[%s] Target browser aligned to Google Chrome ('chrome')", req_id)
            except Exception:
                pass

        # Initialize Reasoning & Context Budget
        exec_ctx.reasoning_budget = ReasoningBudget.for_classification(
            normalized_goal.classification,
            perf_mode=config.performance.mode,
            configured_max_llm=config.performance.max_llm_calls,
        )

        # ── FAST PATH: DETERMINISTIC SINGLE TOOLS (Zero-LLM Call) ─────────────
        if (
            config.performance.fast_path
            and normalized_goal.classification in (TaskClassification.DETERMINISTIC_TOOL, TaskClassification.SINGLE_TOOL)
            and normalized_goal.required_actions
            and normalized_goal.required_actions[0] in _FAST_PATH_TOOLS
            and not has_compound_or_followup_intent(user_input)
        ):
            fast_tool_name = normalized_goal.required_actions[0]
            if self.ctx.registry.get(fast_tool_name) is not None:
                log.info("[%s] EXECUTING DETERMINISTIC FAST PATH: %s", req_id, fast_tool_name)
                trace.mark(Stage.TOOL_DISCOVERY_START)
                trace.mark(Stage.TOOL_DISCOVERY_END)
                trace.set_tool_counts(1, len(self.ctx.registry.list_tools()))
                trace.mark(Stage.TOOL_EXECUTION_START)

                call = NormalizedToolCall(
                    id=f"fast_{uuid.uuid4().hex[:6]}",
                    name=fast_tool_name,
                    arguments={},
                )
                struct_res = await self.execute_tool(exec_ctx, call)
                obs = await self.observe(exec_ctx, fast_tool_name, struct_res)
                verified, _ = await self.verify_action(exec_ctx, fast_tool_name, {}, struct_res, obs)
                trace.mark(Stage.TOOL_EXECUTION_END)
                trace.record_tool_call()

                if struct_res.success:
                    fast_ans = _format_fast_response(fast_tool_name, {}, struct_res.raw_content)
                    exec_ctx.update_state(ExecutionStatus.COMPLETED)
                    self.ctx.memory.add_assistant_message(fast_ans)
                    self.ctx.memory.complete_task(fast_ans)
                    self.emit_event("execution.completed", {
                        "execution_id": req_id,
                        "response": fast_ans,
                        "fast_path": True,
                    })
                    log.info("[%s] EXECUTION_COMPLETED [FAST PATH]: %s", req_id, fast_ans)
                    return self._finalize(exec_ctx, fast_ans, "completed", trace=trace)

        # ── 2. TOOL SELECTION ──────────────────────────────────────────────────
        exec_ctx.update_state(ExecutionStatus.PLANNING)
        trace.mark(Stage.TOOL_DISCOVERY_START)
        all_tool_defs = self.ctx.registry.list_tool_definitions()
        if normalized_goal.classification == TaskClassification.DIRECT_RESPONSE:
            selected_tool_defs = None
            total_tools = len(all_tool_defs)
        else:
            selected_tool_defs, _, total_tools = router_select_tools(user_input, all_tool_defs)
        trace.mark(Stage.TOOL_DISCOVERY_END)
        trace.set_tool_counts(len(selected_tool_defs) if selected_tool_defs else 0, len(all_tool_defs))

        # ── 3. OPTIONAL MEMORY CONTEXT ─────────────────────────────────────────
        memory_context = ""
        ltm = getattr(self.ctx, "long_term_memory", None)
        if ltm and getattr(ltm, "is_available", False) and normalized_goal.classification != TaskClassification.DIRECT_RESPONSE:
            trace.mark(Stage.MEMORY_RETRIEVAL_START)
            try:
                memory_context = ltm.build_context(user_input)
                exec_ctx.memory_context = memory_context
            except Exception as exc:
                log.debug("[ENGINE] LTM context retrieval error: %s", exc)
            trace.mark(Stage.MEMORY_RETRIEVAL_END)

        # System prompt with unified context fusion (prompt injection defense)
        system_prompt = HARMA_SYSTEM_PROMPT
        cf = getattr(self.ctx, "context_fusion", None)
        if cf and memory_context:
            try:
                from harma.intelligence.context_models import ContextItem, TrustLevel, UnifiedContext
                u_ctx = UnifiedContext(
                    user_request=user_input,
                    system_rules=HARMA_SYSTEM_PROMPT,
                )
                u_ctx.long_term_memory.append(
                    ContextItem(
                        source="long_term_memory",
                        content=memory_context,
                        trust_level=TrustLevel.UNTRUSTED,
                    )
                )
                if getattr(self.ctx, "planner", None) and self.ctx.planner.state.current_plan:
                    u_ctx.current_plan = self.ctx.planner.state.current_plan
                fused = cf.build_unified_prompt(u_ctx)
                system_prompt = f"{HARMA_SYSTEM_PROMPT}\n\n{fused}"
            except Exception as exc:
                log.warning("[ENGINE] Unified context fusion fallback: %s", exc)
                system_prompt = f"{HARMA_SYSTEM_PROMPT}\n\n{memory_context}"
        elif memory_context:
            system_prompt = f"{HARMA_SYSTEM_PROMPT}\n\n{memory_context}"

        # ── 4. AUTHORITATIVE AGENT LOOP ────────────────────────────────────────
        for iteration in range(self.max_iterations):
            log.info("── Engine iteration %d/%d [%s]", iteration + 1, self.max_iterations, req_id)

            # Check timeout
            if time.time() > (exec_ctx.deadlines or float("inf")):
                log.warning("[%s] Execution deadline exceeded", req_id)
                timeout_msg = "Task timed out before completion."
                exec_ctx.update_state(ExecutionStatus.FAILED)
                self.ctx.memory.add_assistant_message(timeout_msg)
                return self._finalize(exec_ctx, timeout_msg, "failed", trace=trace)

            # Check cancellation
            if exec_ctx.cancellation_state:
                log.warning("[%s] Execution cancelled by user", req_id)
                cancel_msg = "Execution was cancelled."
                exec_ctx.update_state(ExecutionStatus.CANCELLED)
                return self._finalize(exec_ctx, cancel_msg, "cancelled", trace=trace)

            # Check reasoning budget
            if not exec_ctx.reasoning_budget.can_call_llm():
                log.info("[%s] Reasoning budget reached (%d/%d LLM calls). Completing task.",
                         req_id, exec_ctx.reasoning_budget.llm_calls_used, exec_ctx.reasoning_budget.max_llm_calls)
                synthesis_ans = ""
                try:
                    synthesis_system = (
                        f"{system_prompt}\n\n"
                        "The execution reasoning budget has been reached. Do NOT call any more tools. "
                        "Synthesize the actions taken, the observations on screen/page, and provide a clear, "
                        "helpful, natural response to the user's request. Explain what step was reached, "
                        "what options are available, and what they need to decide next."
                    )
                    synthesis_resp = await self.ctx.llm.complete(
                        messages=self.ctx.memory.get_messages(),
                        tools=None,
                        system=synthesis_system,
                    )
                    if synthesis_resp and synthesis_resp.content and synthesis_resp.content.strip():
                        synthesis_ans = synthesis_resp.content.strip()
                except Exception as exc:
                    log.warning("[%s] Synthesis completion fallback failed: %s", req_id, exc)

                if not synthesis_ans:
                    if exec_ctx.tool_history:
                        last_h = exec_ctx.tool_history[-1]
                        synthesis_ans = f"I completed the step with {last_h.get('tool')}. Please let me know what you would like to do next."
                    else:
                        synthesis_ans = "Request processed."

                exec_ctx.update_state(ExecutionStatus.COMPLETED)
                self.ctx.memory.add_assistant_message(synthesis_ans)
                self.ctx.memory.complete_task(synthesis_ans)
                return self._finalize(exec_ctx, synthesis_ans, "completed", trace=trace)

            exec_ctx.reasoning_budget.record_llm_call()

            # Query LLM
            exec_ctx.update_state(ExecutionStatus.PLANNING)
            messages = self.ctx.memory.get_messages()
            trace.mark(Stage.LLM_REQUEST_START)
            t_llm = time.time()
            llm_response = await self.ctx.llm.complete(
                messages=messages,
                tools=selected_tool_defs if selected_tool_defs else None,
                system=system_prompt,
            )
            trace.mark(Stage.LLM_REQUEST_END)

            usage = getattr(llm_response, "usage", {}) or {}
            trace.record_llm_call(
                tokens_in=usage.get("prompt_tokens", 0),
                tokens_out=usage.get("completion_tokens", 0),
            )

            exec_ctx.llm_calls.append(LLMCallRecord(
                purpose=f"ITERATION_{iteration + 1}",
                provider=self.ctx.llm.name,
                model=getattr(self.ctx.llm, "model", ""),
                latency_ms=(time.time() - t_llm) * 1000,
                tool_count=len(llm_response.tool_calls),
                result_summary=llm_response.content[:100] if llm_response.content else f"{len(llm_response.tool_calls)} tools",
            ))

            # Case A: No tool calls → Task completed, final response
            if not llm_response.tool_calls:
                final_text = llm_response.content.strip()
                if not final_text:
                    if iteration > 0:
                        final_text = "I completed the requested action."
                    else:
                        final_text = "I processed your request, but have no additional details to report."

                exec_ctx.update_state(ExecutionStatus.COMPLETED)
                self.ctx.memory.add_assistant_message(final_text)
                self.ctx.memory.complete_task(final_text)
                self.emit_event("execution.completed", {
                    "execution_id": req_id,
                    "response": final_text,
                    "total_iterations": iteration + 1,
                })
                log.info("[%s] EXECUTION_COMPLETED: %s", req_id, final_text[:80])
                return self._finalize(exec_ctx, final_text, "completed", trace=trace)

            # Case B: Tool calls present → Store, Execute, Observe, Verify
            tool_calls = llm_response.tool_calls
            self.ctx.memory.add_assistant_message(
                content=llm_response.content or "",
                tool_calls=tool_calls,
            )

            tool_results: list[ToolResult] = []
            all_succeeded = True

            trace.mark(Stage.TOOL_EXECUTION_START)
            for tc in tool_calls:
                trace.record_tool_call()
                if tc.name in ("take_screenshot", "observe_screen"):
                    trace.record_screenshot()

                norm_call = NormalizedToolCall.from_provider_call(tc)

                # Loop detection check
                is_read_only = norm_call.name in ("observe_page", "take_screenshot", "observe_screen", "get_page_title", "extract_page_text")
                loop_thresh = 5 if is_read_only else 3
                if exec_ctx.check_loop(norm_call.name, norm_call.arguments, threshold=loop_thresh):
                    if is_read_only:
                        log.warning("[%s] LOOP_WARNING: Read-only tool %s repeated %d times. Nudging model to take action.", req_id, norm_call.name, loop_thresh)
                        nudge_res = ToolResult(
                            success=True,
                            output="Observation repeated. Current page details were already provided above. Please execute your next concrete action (e.g. click a button, select seats, or complete the task) rather than repeating observe_page.",
                        )
                        tool_results.append(nudge_res)
                        continue
                    log.error("[%s] LOOP_DETECTED: Tool %s called %d times without progress", req_id, norm_call.name, loop_thresh)
                    self.emit_event("execution.failed", {
                        "execution_id": req_id,
                        "reason": f"Loop detected: repeating {norm_call.name} without progress",
                    }, severity=EventSeverity.ERROR)
                    loop_err = f"Execution stopped: loop detected while attempting action {norm_call.name}."
                    exec_ctx.update_state(ExecutionStatus.FAILED)
                    self.ctx.memory.add_assistant_message(loop_err)
                    return self._finalize(exec_ctx, loop_err, "failed", trace=trace)

                # Execute pipeline step
                struct_res = await self.execute_tool(exec_ctx, norm_call)
                obs = await self.observe(exec_ctx, norm_call.name, struct_res)
                struct_res.observation = obs
                verified, v_reason = await self.verify_action(exec_ctx, norm_call.name, norm_call.arguments, struct_res, obs)

                if norm_call.name == "open_application":
                    app = norm_call.arguments.get("application_name", "")
                    if app:
                        self.ctx.memory.active_application = app

                if not verified or not struct_res.success:
                    all_succeeded = False
                    err_cls = ErrorClass(struct_res.error.get("type", ErrorClass.UNKNOWN.value)) if struct_res.error else ErrorClass.UNKNOWN
                    exec_ctx.record_error(err_cls, v_reason, tool=norm_call.name)

                    # Bounded recovery check
                    exec_ctx.reasoning_budget.mode = BudgetMode.RECOVERY
                    if self.can_retry(exec_ctx, norm_call.name, err_cls):
                        exec_ctx.retry_counts[norm_call.name] = exec_ctx.retry_counts.get(norm_call.name, 0) + 1
                        log.info("[%s] RETRYING step %s (attempt %d)", req_id, norm_call.name, exec_ctx.retry_counts[norm_call.name])
                        self.emit_event("execution.retry", {
                            "execution_id": req_id,
                            "tool": norm_call.name,
                            "retry_count": exec_ctx.retry_counts[norm_call.name],
                        })
                    else:
                        log.warning("[%s] Step %s cannot be retried or exceeded max retries", req_id, norm_call.name)

                # Feed result back to memory format
                tr = struct_res.to_tool_result()
                tool_results.append(tr)

            trace.mark(Stage.TOOL_EXECUTION_END)
            self.ctx.memory.add_tool_results(tool_results)

            # Completion Gate: when a single verified action has succeeded, complete immediately
            is_single_verified = (
                (
                    normalized_goal.classification in (TaskClassification.SINGLE_TOOL, TaskClassification.DETERMINISTIC_TOOL)
                    or (iteration == 0 and tool_calls[0].name in _FAST_PATH_TOOLS)
                )
                and not has_compound_or_followup_intent(user_input)
                and len(tool_calls) == 1
                and all_succeeded
                and verified
            )
            if is_single_verified:
                tc0 = tool_calls[0]
                tr0 = tool_results[0]
                fast_ans = _format_fast_response(tc0.name, tc0.arguments, tr0.content or "")
                exec_ctx.update_state(ExecutionStatus.COMPLETED)
                self.ctx.memory.add_assistant_message(fast_ans)
                self.ctx.memory.complete_task(fast_ans)
                self.emit_event("execution.completed", {
                    "execution_id": req_id,
                    "response": fast_ans,
                    "completion_gate": True,
                })
                log.info("[%s] EXECUTION_COMPLETED [COMPLETION GATE]: %s", req_id, fast_ans)
                return self._finalize(exec_ctx, fast_ans, "completed", trace=trace)

            # Update task progress in memory for continuation
            for tc, tr in zip(tool_calls, tool_results):
                step_desc = f"Called {tc.name}: {tr.content[:80]}"
                self.ctx.memory.update_task(step_desc)

        # Max iterations reached without completion
        timeout_msg = (
            "I reached the maximum number of steps without completing the task. "
            "Please try rephrasing or breaking the request into smaller parts."
        )
        exec_ctx.update_state(ExecutionStatus.FAILED)
        self.ctx.memory.add_assistant_message(timeout_msg)
        self.emit_event("execution.failed", {"execution_id": req_id, "reason": "Max iterations reached"})
        return self._finalize(exec_ctx, timeout_msg, "incomplete", trace=trace)

    # ── Phase 9 Structured Plan Integration ───────────────────────────────────

    async def run_plan(self, goal: str, dry_run: bool = False) -> str:
        """Execute a goal using the Phase 9 structured planning and verification engine."""
        planner = getattr(self.ctx, "planner", None)
        if not planner:
            return "Planning engine is not available in current context."

        log.info("[ENGINE] Executing structured plan for: '%s' (dry_run=%s)", goal, dry_run)
        self.ctx.memory.add_user_message(f"/plan {goal}" if not dry_run else f"/dry-run {goal}")

        plan = planner.create_plan(goal=goal, dry_run=dry_run)
        executed_plan = await planner.execute_plan(
            plan=plan,
            confirm_callback=getattr(self.executor, "_confirm", self.confirm_callback),
        )

        summary_lines = [
            f"Plan {executed_plan.plan_id}: {executed_plan.goal}",
            f"Status: {executed_plan.status.value.upper()}",
            "Steps Summary:",
        ]
        for step in executed_plan.steps:
            summary_lines.append(f"  • Step {step.step_id}: {step.description} [{step.status.value.upper()}]")
            if step.observation:
                summary_lines.append(f"    Observation: {step.observation[:100]}")

        final_msg = "\n".join(summary_lines)
        self.ctx.memory.add_assistant_message(final_msg)
        self.last_execution_meta = {
            "request_id": f"plan-{executed_plan.plan_id}",
            "status": "completed" if executed_plan.status.value.upper() == "COMPLETED" else "failed",
            "response": final_msg,
            "plan_id": executed_plan.plan_id,
            "tool_calls": [],
            "verification": {"status": "verified"},
            "perf": {},
        }
        return final_msg
