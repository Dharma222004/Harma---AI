"""
Harma Execution State Models & Structured Context — Framework V2

Defines:
  - ExecutionStatus (13 explicit lifecycle states)
  - TaskClassification (complexity & autonomy categories)
  - ErrorClass (recovery taxonomy)
  - NormalizedGoal, NormalizedToolCall, StructuredToolResult
  - ExecutionContext (single authoritative runtime state)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from harma.llm.provider import ToolCall, ToolResult


class ExecutionStatus(str, Enum):
    """Explicit state machine states for Harma's single authoritative execution engine."""
    IDLE                     = "idle"
    UNDERSTANDING            = "understanding"
    PLANNING                 = "planning"
    WAITING_FOR_TOOL         = "waiting_for_tool"
    EXECUTING_TOOL           = "executing_tool"
    OBSERVING                = "observing"
    VERIFYING                = "verifying"
    REPLANNING               = "replanning"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    COMPLETED                = "completed"
    FAILED                   = "failed"
    CANCELLED                = "cancelled"
    PAUSED                   = "paused"


class TaskClassification(str, Enum):
    """Categorization of requests determining execution strategy and planning overhead."""
    DIRECT_RESPONSE        = "direct_response"       # Simple conversational, zero tool calls
    DETERMINISTIC_TOOL     = "deterministic_tool"    # Fast-path deterministic tool (time, sysinfo, etc.)
    SINGLE_TOOL            = "single_tool"           # Single tool action (app launch, search, etc.)
    MULTI_TOOL             = "multi_tool"            # Multiple tools needed, simple workflow
    MULTI_STEP             = "multi_step"            # Complex, multi-turn task requiring full loop
    HIGH_RISK              = "high_risk"             # Potentially destructive / sensitive
    REQUIRES_CONFIRMATION  = "requires_confirmation" # Explicit confirmation mandatory
    BACKGROUND_TASK        = "background_task"       # Asynchronous decoupled task
    AUTONOMOUS_TASK        = "autonomous_task"       # Scheduled/proactive task from Phase 7


class ErrorClass(str, Enum):
    """Structured taxonomy of runtime execution failures."""
    TRANSIENT             = "transient"              # Network glitches, busy resources (retryable)
    INVALID_ARGUMENT      = "invalid_argument"       # Malformed or missing arguments (re-prompt LLM)
    ELEMENT_NOT_FOUND     = "element_not_found"      # UI element / app missing (observe & re-try)
    TIMEOUT               = "timeout"                # Action exceeded deadline (backoff / replan)
    AUTHENTICATION        = "authentication"         # Credentials required (halt & prompt user)
    PERMISSION_DENIED     = "permission_denied"      # Security/autonomy rejection (halt)
    RESOURCE_UNAVAILABLE  = "resource_unavailable"   # Missing peripheral or display (replan)
    ENVIRONMENT_CHANGED   = "environment_changed"    # Unexpected window or tab state (observe & replan)
    UNKNOWN               = "unknown"                # Unclassified failure (bounded retry)


@dataclass
class NormalizedGoal:
    """Structured representation of a parsed user request."""
    goal: str
    required_actions: list[str] = field(default_factory=list)
    requires_tools: bool = True
    risk_level: str = "low"  # low | medium | high
    classification: TaskClassification = TaskClassification.SINGLE_TOOL
    constraints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "required_actions": self.required_actions,
            "requires_tools": self.requires_tools,
            "risk_level": self.risk_level,
            "classification": self.classification.value,
            "constraints": self.constraints,
        }


@dataclass
class NormalizedToolCall:
    """Provider-agnostic tool call representation."""
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_provider_call(cls, tc: ToolCall) -> NormalizedToolCall:
        return cls(id=tc.id, name=tc.name, arguments=dict(tc.arguments or {}))

    def to_provider_call(self) -> ToolCall:
        return ToolCall(id=self.id, name=self.name, arguments=self.arguments)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "arguments": self.arguments}


@dataclass
class StructuredToolResult:
    """Normalized output from any executed tool."""
    success: bool
    tool: str
    data: dict[str, Any] = field(default_factory=dict)
    observation: dict[str, Any] = field(default_factory=dict)
    error: Optional[dict[str, Any]] = None  # {"type": ErrorClass.value, "message": str}
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_content: str = ""
    tool_call_id: str = ""

    def to_tool_result(self) -> ToolResult:
        """Convert to the LLMProvider ToolResult for memory and model consumption."""
        import json
        payload: dict[str, Any] = {
            "success": self.success,
            "tool": self.tool,
            "data": self.data,
        }
        if self.observation:
            payload["observation"] = self.observation
        if self.error:
            payload["error"] = self.error
        if self.metadata:
            payload["metadata"] = self.metadata

        content = self.raw_content if self.raw_content else json.dumps(payload)
        return ToolResult(
            tool_call_id=self.tool_call_id or f"call_{uuid.uuid4().hex[:6]}",
            name=self.tool,
            content=content,
            is_error=not self.success,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "tool": self.tool,
            "data": self.data,
            "observation": self.observation,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class LLMCallRecord:
    """Audit record for every interaction with an LLM."""
    purpose: str
    provider: str
    model: str
    latency_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    tool_count: int = 0
    result_summary: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "provider": self.provider,
            "model": self.model,
            "latency_ms": round(self.latency_ms, 2),
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "tool_count": self.tool_count,
            "result_summary": self.result_summary[:120],
            "timestamp": self.timestamp,
        }


class BudgetMode(str, Enum):
    """Explicit reasoning budget operational states."""
    FAST     = "FAST"      # Deterministic / simple actions / known workflows
    NORMAL   = "NORMAL"    # Standard multi-step, browser, MCP workflows
    DEEP     = "DEEP"      # Complex planning, ambiguous requests, difficult recovery
    RECOVERY = "RECOVERY"  # Deviation from expected plan, bounded self-correction


_CONSEQUENTIAL_TOOLS: frozenset[str] = frozenset({
    "delete_file", "delete_task", "create_task", "schedule_task",
    "send_email", "send_message", "post_tweet", "write_file",
})


@dataclass
class ReasoningBudget:
    """
    Enforces dynamic limits on LLM reasoning and execution cycles.
    Prevents endless LLM ping-pong loops while allowing complex multi-step reasoning.
    """
    mode: BudgetMode = BudgetMode.NORMAL
    max_llm_calls: int = 4
    max_replans: int = 2
    max_context_tokens: int = 16000
    max_execution_time_s: float = 120.0
    max_tool_steps: int = 12

    llm_calls_used: int = 0
    replans_used: int = 0
    tool_steps_used: int = 0

    @classmethod
    def for_classification(
        cls,
        classification: TaskClassification,
        perf_mode: str = "balanced",
        configured_max_llm: Optional[int] = None,
    ) -> "ReasoningBudget":
        if classification == TaskClassification.DIRECT_RESPONSE:
            return cls(max_llm_calls=1, max_replans=0, max_tool_steps=0, mode=BudgetMode.FAST)
        elif classification == TaskClassification.DETERMINISTIC_TOOL:
            return cls(max_llm_calls=0, max_replans=0, max_tool_steps=1, mode=BudgetMode.FAST)  # fast-path, 0 LLM calls!
        elif classification == TaskClassification.SINGLE_TOOL:
            limit = 1 if perf_mode == "fast" else 2
            return cls(max_llm_calls=limit, max_replans=1, max_tool_steps=3, mode=BudgetMode.FAST)
        elif classification == TaskClassification.MULTI_STEP:
            limit = max(configured_max_llm or 0, 15 if perf_mode == "fast" else 100)
            return cls(max_llm_calls=limit, max_replans=10, max_tool_steps=100, mode=BudgetMode.NORMAL)
        else:  # MULTI_TOOL / COMPLEX / HIGH_RISK
            limit = max(configured_max_llm or 0, 20 if perf_mode == "fast" else 100)
            return cls(max_llm_calls=limit, max_replans=10, max_tool_steps=100, mode=BudgetMode.DEEP)

    def can_call_llm(self) -> bool:
        return self.llm_calls_used < self.max_llm_calls

    def record_llm_call(self) -> None:
        self.llm_calls_used += 1

    def can_replan(self) -> bool:
        return self.replans_used < self.max_replans

    def record_replan(self) -> None:
        self.replans_used += 1


@dataclass
class ContextBudget:
    """Tracks token allocation across system instructions, schemas, history, and observations."""
    max_tokens: int = 16000
    system_tokens: int = 0
    tool_schema_tokens: int = 0
    history_tokens: int = 0
    observation_tokens: int = 0
    memory_tokens: int = 0
    user_tokens: int = 0
    reserved_output_tokens: int = 1024

    def total_input_tokens(self) -> int:
        return (
            self.system_tokens
            + self.tool_schema_tokens
            + self.history_tokens
            + self.observation_tokens
            + self.memory_tokens
            + self.user_tokens
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "total_input_tokens": self.total_input_tokens(),
            "system_tokens": self.system_tokens,
            "tool_schema_tokens": self.tool_schema_tokens,
            "history_tokens": self.history_tokens,
            "observation_tokens": self.observation_tokens,
            "memory_tokens": self.memory_tokens,
            "user_tokens": self.user_tokens,
            "max_tokens": self.max_tokens,
        }


@dataclass
class ExecutionContext:
    """
    Unified, single execution context carrying runtime state across all pipeline stages.
    """
    execution_id: str = field(default_factory=lambda: f"exec_{uuid.uuid4().hex[:8]}")
    user_request: str = ""
    normalized_goal: Optional[NormalizedGoal] = None
    constraints: list[str] = field(default_factory=list)
    plan: Optional[Any] = None
    current_step: int = 0
    completed_steps: list[dict[str, Any]] = field(default_factory=list)
    pending_steps: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    tool_history: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=lambda: {"status": "unverified"})
    permissions: dict[str, Any] = field(default_factory=dict)
    memory_context: str = ""
    environment_context: dict[str, Any] = field(default_factory=dict)
    deadlines: Optional[float] = None
    cancellation_state: bool = False
    is_paused: bool = False
    retry_counts: dict[str, int] = field(default_factory=dict)
    state: ExecutionStatus = ExecutionStatus.IDLE
    state_history: list[dict[str, Any]] = field(default_factory=list)
    autonomy_level: str = "supervised"
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    llm_calls: list[LLMCallRecord] = field(default_factory=list)
    loop_history: list[str] = field(default_factory=list)
    final_response: str = ""
    reasoning_budget: ReasoningBudget = field(default_factory=ReasoningBudget)
    context_budget: ContextBudget = field(default_factory=ContextBudget)

    def __post_init__(self) -> None:
        if not self.state_history:
            self.state_history.append({
                "from_state": None,
                "to_state": self.state.value,
                "timestamp": self.started_at,
            })

    @property
    def current_state(self) -> ExecutionStatus:
        return self.state

    def update_state(self, new_state: ExecutionStatus) -> None:
        old_state = self.state
        self.state = new_state
        self.updated_at = time.time()
        self.state_history.append({
            "from_state": old_state.value,
            "to_state": new_state.value,
            "timestamp": self.updated_at,
        })

    def record_step_completed(self, step_info: dict[str, Any]) -> None:
        self.completed_steps.append(step_info)
        self.current_step += 1
        self.updated_at = time.time()

    def record_observation(self, obs: dict[str, Any]) -> None:
        self.observations.append(obs)
        self.updated_at = time.time()

    def record_error(self, err_type: ErrorClass, message: str, tool: str = "") -> None:
        self.errors.append({
            "type": err_type.value,
            "message": message,
            "tool": tool,
            "timestamp": time.time(),
        })
        self.updated_at = time.time()

    def record_tool_execution(self, tool_name: str, args: dict[str, Any], result: StructuredToolResult) -> None:
        self.tool_history.append({
            "tool": tool_name,
            "arguments": args,
            "success": result.success,
            "error": result.error,
            "timestamp": time.time(),
        })
        fp = f"{tool_name}:{sorted(args.items())}"
        self.loop_history.append(fp)
        self.updated_at = time.time()

    def check_loop(self, tool_name: str, args: dict[str, Any], threshold: int = 3, record: bool = False) -> bool:
        """Return True if the exact same tool and arguments were executed threshold times consecutively."""
        fp = f"{tool_name}:{sorted(args.items())}"
        if record:
            self.loop_history.append(fp)
            history = self.loop_history
        else:
            history = self.loop_history + [fp]
        recent = history[-threshold:]
        return len(recent) >= threshold and all(item == fp for item in recent)

    def has_consequential_succeeded(self, tool_name: str, args: dict[str, Any]) -> bool:
        """
        Check whether this specific consequential tool action has already succeeded
        in this execution context, guarding against duplicate side-effects.
        """
        if tool_name not in _CONSEQUENTIAL_TOOLS:
            return False
        fp = f"{tool_name}:{sorted(args.items())}"
        for entry in self.tool_history:
            if entry.get("success") and f"{entry.get('tool')}:{sorted(entry.get('arguments', {}).items())}" == fp:
                return True
        return False

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "user_request": self.user_request,
            "current_state": self.state.value,
            "status": self.state.value,
            "current_step": self.current_step,
            "total_completed": len(self.completed_steps),
            "total_tools_called": len(self.tool_history),
            "verification": self.verification,
            "duration_ms": round((time.time() - self.started_at) * 1000, 2),
            "llm_calls": len(self.llm_calls),
            "llm_call_records": [c.to_dict() for c in self.llm_calls],
            "total_errors": len(self.errors),
            "errors": len(self.errors),
            "reasoning_budget": {
                "mode": self.reasoning_budget.mode.value,
                "max_llm_calls": self.reasoning_budget.max_llm_calls,
                "llm_calls_used": self.reasoning_budget.llm_calls_used,
                "max_replans": self.reasoning_budget.max_replans,
                "replans_used": self.reasoning_budget.replans_used,
            },
            "context_budget": self.context_budget.to_dict(),
        }
