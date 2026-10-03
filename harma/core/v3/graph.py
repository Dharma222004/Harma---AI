"""
Harma Runtime V3 — Execution Graph, Completion/Failure Gates and deterministic responses
(spec §17, §18, §52, §58, §59)

The graph — not the LLM — decides what happens next whenever the runtime already knows.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from harma.core.v3 import toolmeta
from harma.core.v3.recovery import FailureClass, failure_message, parse_failure
from harma.core.v3.state import HarmaRunState, RunStatus, StepStatus, VerificationState


class Node(str, Enum):
    INTENT = "IntentNode"
    ROUTING = "RoutingNode"
    EXPERIENCE_RETRIEVAL = "ExperienceRetrievalNode"
    STRATEGY_SELECTION = "StrategySelectionNode"
    PLANNING = "PlanningNode"
    PERMISSION = "PermissionNode"
    CONFIRMATION = "ConfirmationNode"
    TOOL_EXECUTION = "ToolExecutionNode"
    OBSERVATION = "ObservationNode"
    VERIFICATION = "VerificationNode"
    RECOVERY = "RecoveryNode"
    REPLANNING = "ReplanningNode"
    LEARNING = "LearningNode"
    COMPLETION = "CompletionNode"
    FAILURE = "FailureNode"


NODE_STATUS: dict[Node, RunStatus] = {
    Node.INTENT: RunStatus.UNDERSTANDING,
    Node.ROUTING: RunStatus.ROUTING,
    Node.EXPERIENCE_RETRIEVAL: RunStatus.RETRIEVING_EXPERIENCE,
    Node.STRATEGY_SELECTION: RunStatus.SELECTING_STRATEGY,
    Node.PLANNING: RunStatus.PLANNING,
    Node.PERMISSION: RunStatus.EXECUTING,
    Node.CONFIRMATION: RunStatus.WAITING_FOR_CONFIRMATION,
    Node.TOOL_EXECUTION: RunStatus.EXECUTING,
    Node.OBSERVATION: RunStatus.OBSERVING,
    Node.VERIFICATION: RunStatus.VERIFYING,
    Node.RECOVERY: RunStatus.RECOVERING,
    Node.REPLANNING: RunStatus.REPLANNING,
    Node.LEARNING: RunStatus.LEARNING,
    Node.COMPLETION: RunStatus.COMPLETED,
    Node.FAILURE: RunStatus.FAILED,
}

# Allowed transitions (documentation + runtime assertion in debug runs).
TRANSITIONS: dict[Node, frozenset[Node]] = {
    Node.INTENT: frozenset({Node.ROUTING, Node.EXPERIENCE_RETRIEVAL, Node.STRATEGY_SELECTION, Node.LEARNING, Node.COMPLETION}),
    Node.ROUTING: frozenset({Node.EXPERIENCE_RETRIEVAL, Node.STRATEGY_SELECTION}),
    Node.EXPERIENCE_RETRIEVAL: frozenset({Node.STRATEGY_SELECTION}),
    Node.STRATEGY_SELECTION: frozenset({Node.PLANNING, Node.TOOL_EXECUTION, Node.COMPLETION, Node.LEARNING}),
    Node.PLANNING: frozenset({Node.TOOL_EXECUTION, Node.COMPLETION, Node.FAILURE}),
    Node.PERMISSION: frozenset({Node.CONFIRMATION, Node.TOOL_EXECUTION, Node.RECOVERY}),
    Node.CONFIRMATION: frozenset({Node.TOOL_EXECUTION, Node.RECOVERY}),
    Node.TOOL_EXECUTION: frozenset({Node.OBSERVATION, Node.RECOVERY}),
    Node.OBSERVATION: frozenset({Node.VERIFICATION}),
    Node.VERIFICATION: frozenset({Node.TOOL_EXECUTION, Node.OBSERVATION, Node.PLANNING, Node.RECOVERY, Node.LEARNING}),
    Node.RECOVERY: frozenset({Node.TOOL_EXECUTION, Node.REPLANNING, Node.LEARNING}),
    Node.REPLANNING: frozenset({Node.TOOL_EXECUTION, Node.LEARNING}),
    Node.LEARNING: frozenset({Node.COMPLETION, Node.FAILURE}),
    Node.COMPLETION: frozenset(),
    Node.FAILURE: frozenset(),
}


def enter(state: HarmaRunState, node: Node, reason: str = "") -> None:
    """Explicit, observable node/state transition."""
    from harma.core.v3.events import emit
    target = NODE_STATUS[node]
    if state.status != target or state.current_node != node.value:
        prev = state.status
        state.transition(target, node.value, reason)
        emit(state, "StateTransition", {"from": prev.value, "to": target.value, "node": node.value, "reason": reason})


def next_after_verification(verdict: str, *, recoverable: bool, requires_new_plan: bool, has_pending: bool) -> Node:
    """Deterministic transition after VerificationNode (spec §18)."""
    if verdict in ("verified", "not_required", "unverified"):
        return Node.TOOL_EXECUTION if has_pending else Node.LEARNING
    if verdict == "inconclusive":
        return Node.OBSERVATION
    if recoverable:
        return Node.RECOVERY
    if requires_new_plan:
        return Node.REPLANNING
    return Node.FAILURE


# ── Gates ─────────────────────────────────────────────────────────────────────

class CompletionGate:
    """
    A run may complete only when: every planned step finished, every FAILED step was superseded
    by recovery, and no consequential side effect is unresolved. The outcome is `verified` only if
    every achieved step is VERIFIED or NOT_REQUIRED; otherwise it is `unverified` (and the
    response says so honestly; unverified runs never reinforce learned procedures).
    """

    @staticmethod
    def evaluate(state: HarmaRunState) -> tuple[bool, str, str]:
        steps = state.plan.steps
        if any(s.status in (StepStatus.PENDING, StepStatus.RUNNING) for s in steps):
            return False, "", "steps still pending"
        for s in steps:
            if s.status == StepStatus.FAILED and not (s.error or {}).get("superseded"):
                return False, "", f"unrecovered failure at {s.tool}"
        achieved = [s for s in steps if s.status == StepStatus.SUCCEEDED]
        if not achieved:
            return True, "answered", "no actions were required"
        ok_states = (VerificationState.VERIFIED, VerificationState.NOT_REQUIRED)
        if all(s.verification in ok_states for s in achieved):
            return True, "verified", "all steps verified"
        return True, "unverified", "some effects could not be independently verified"


class FailureGate:
    """Fail only when safe recovery and replanning are exhausted or the path is impossible."""

    @staticmethod
    def should_fail(decision_action: str, failure: FailureClass, state: HarmaRunState, max_replans: int) -> bool:
        if decision_action == "fail":
            return True
        if decision_action == "replan" and state.replan_count >= max_replans:
            return True
        return False


# ── Deterministic responses (spec §52) ───────────────────────────────────────

_FAST_TEMPLATES = {
    "open_application": "Done — {v} is open.",
    "close_application": "Done — I closed {v}.",
    "focus_application": "Done — {v} is in focus.",
}


def _primary_value(args: dict[str, Any]) -> str:
    for v in (args or {}).values():
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


class ResponseComposer:
    @staticmethod
    def completed(state: HarmaRunState) -> str:
        achieved = [s for s in state.plan.steps if s.status == StepStatus.SUCCEEDED]
        dup = set(state.working_memory.get("duplicate_steps", []))
        # Self-describing informational results are the answer.
        info = [s.result_summary for s in achieved if s.tool in toolmeta.SELF_DESCRIBING and s.result_summary]
        actions = [s for s in achieved if not toolmeta.is_read_only(s.tool) and s.step_id not in dup]
        unverified = state.final_outcome == "unverified"
        if len(achieved) == 1 and achieved[0].tool in _FAST_TEMPLATES and not unverified:
            v = _primary_value(achieved[0].arguments)
            return _FAST_TEMPLATES[achieved[0].tool].format(v=v) if v else "Done."
        parts: list[str] = []
        if info:
            parts.append("\n".join(info))
        if actions:
            desc = ", then ".join(toolmeta.humanize_step(s.tool, s.arguments) for s in actions)
            parts.append(f"Done — {desc}.")
        if not parts:
            parts.append("Done.")
        if unverified:
            parts.append("(I couldn't independently verify every effect — please check the result.)")
        return " ".join(parts) if not info else "\n".join(parts)

    @staticmethod
    def failed(state: HarmaRunState) -> str:
        err = state.last_error or {}
        failure = parse_failure(state.failure_classification or err.get("type"))
        failed_step = next((s for s in reversed(state.plan.steps) if s.status == StepStatus.FAILED), None)
        tool = failed_step.tool if failed_step else err.get("tool", "")
        reason = failure_message(failure, tool, str(err.get("message", ""))[:160])
        msg = f"I couldn't complete the task because {reason}."
        done = [toolmeta.humanize_step(s.tool, s.arguments) for s in state.plan.steps
                if s.status == StepStatus.SUCCEEDED and not toolmeta.is_read_only(s.tool)]
        if done:
            msg += f" Completed before stopping: {', '.join(done)}."
        return msg

    @staticmethod
    def cancelled(state: HarmaRunState) -> str:
        done = [toolmeta.humanize_step(s.tool, s.arguments) for s in state.plan.steps if s.status == StepStatus.SUCCEEDED]
        return "Cancelled." + (f" Already completed: {', '.join(done)}." if done else "")

    @staticmethod
    def paused(state: HarmaRunState) -> str:
        pending = len(state.plan.pending_steps())
        return f"Paused (run {state.run_id}). {pending} step(s) remaining — resume when ready."

    @staticmethod
    def ask_user(state: HarmaRunState) -> str:
        return "Could you tell me exactly what you'd like me to do (which app, item or person)?"
