"""
Harma Runtime V3 — Tool Runtime (spec §25–27, §30)

The single execution boundary for every tool call:

    Resolve → Validate → Permission → Risk / learned policy → Confirmation → Resource lock
            → Idempotency → Execute (timeout) → Normalize → Evidence → Return

No tool bypasses this boundary — including steps proposed by learned procedures.
Action success is NOT goal success: results leave here with verification_state=PENDING
(or NOT_REQUIRED for read-only tools) and the VerificationEngine decides the rest.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

from harma.config.logging_config import get_logger
from harma.core.v3 import toolmeta
from harma.core.v3.events import emit
from harma.core.v3.experience.feedback import requires_confirmation as learned_requires_confirmation
from harma.core.v3.recovery import FailureClass, classify_error_text, error_payload
from harma.core.v3.resources import ResourceManager
from harma.core.v3.state import HarmaRunState, PlanStep, RunStatus, StepStatus, VerificationState

log = get_logger(__name__)


@dataclass
class ToolOutcome:
    """Normalized tool result (spec §26)."""
    status: str                          # success | error | denied | cancelled | skipped
    action_state: str                    # executed | not_executed | skipped_duplicate
    verification_state: VerificationState
    tool: str
    call_id: str
    result: str = ""
    data: Any = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[dict[str, Any]] = None
    duration_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == "success"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["verification_state"] = self.verification_state.value
        try:
            json.dumps(d["data"])
        except Exception:
            d["data"] = str(self.data)[:500]
        return d


def action_fingerprint(tool: str, arguments: dict[str, Any]) -> str:
    canon = json.dumps({"t": tool, "a": arguments}, sort_keys=True, default=str)
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:16]


def _publish_legacy(event_type: str, payload: dict[str, Any]) -> None:
    """Keep the Control Center's existing tool.started / tool.completed feed working."""
    try:
        from harma.api.events import get_event_bus
        get_event_bus().publish(event_type, source="harma_runner", payload=payload)
    except Exception:
        pass


class ToolRuntime:
    def __init__(
        self,
        ctx: Any,
        resources: ResourceManager,
        confirm_callback: Optional[Callable[[str], str]] = None,
        corrections_provider: Optional[Callable[[], list]] = None,
        checkpoint: Optional[Callable[[HarmaRunState, str], None]] = None,
        tool_timeout_s: float = 120.0,
    ) -> None:
        self.ctx = ctx
        self.resources = resources
        self.confirm_callback = confirm_callback
        self.corrections_provider = corrections_provider or (lambda: [])
        self.checkpoint = checkpoint or (lambda s, r: None)
        self.tool_timeout_s = tool_timeout_s

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _outcome(self, step: PlanStep, call_id: str, status: str, action: str, failure: Optional[FailureClass],
                 message: str = "", t0: float = 0.0) -> ToolOutcome:
        return ToolOutcome(
            status=status, action_state=action,
            verification_state=VerificationState.FAILED if failure else VerificationState.PENDING,
            tool=step.tool, call_id=call_id, result=message,
            error=error_payload(failure, message) if failure else None,
            duration_ms=round((time.perf_counter() - t0) * 1000, 2) if t0 else 0.0,
        )

    def _confirm(self, prompt: str) -> bool:
        if self.confirm_callback is None:
            return False                 # fail safe: no channel to ask → deny
        try:
            answer = self.confirm_callback(prompt)
        except Exception as exc:
            log.warning("[V3][TOOL] Confirmation callback failed: %s", exc)
            return False
        return str(answer or "").strip().lower() in ("y", "yes")

    @staticmethod
    def _validate(tool: Any, args: dict[str, Any]) -> Optional[str]:
        if not isinstance(args, dict):
            return "arguments must be an object"
        for req in toolmeta.required_params(tool):
            if req not in args or args[req] is None:
                return f"missing required argument '{req}'"
        return None

    # ── Main entry ────────────────────────────────────────────────────────────

    async def execute(self, state: HarmaRunState, step: PlanStep) -> ToolOutcome:
        t0 = time.perf_counter()
        call_id = step.llm_call_id or f"v3_{uuid.uuid4().hex[:8]}"
        state.active_tool, state.active_tool_call_id = step.tool, call_id
        step.attempts += 1

        # 1. Resolve
        tool = self.ctx.registry.get(step.tool)
        if tool is None:
            return self._outcome(step, call_id, "error", "not_executed", FailureClass.ELEMENT_NOT_FOUND,
                                 f"Tool '{step.tool}' is not available.", t0)

        # 2. Validate
        problem = self._validate(tool, step.arguments)
        if problem:
            return self._outcome(step, call_id, "error", "not_executed", FailureClass.INVALID_ARGUMENT,
                                 f"Invalid arguments for {step.tool}: {problem}", t0)

        consequential = toolmeta.is_consequential(step.tool, tool)
        fp = action_fingerprint(step.tool, step.arguments)

        # 3. Idempotency — never repeat a consequential side effect that already happened in this run
        if consequential and fp in state.side_effect_fingerprints:
            prior_id = state.side_effect_fingerprints[fp]
            prior = next((s for s in state.plan.steps if s.step_id == prior_id), None)
            if prior is not None and prior.status == StepStatus.SUCCEEDED:
                state.working_memory.setdefault("duplicate_steps", []).append(step.step_id)
                out = ToolOutcome(status="success", action_state="skipped_duplicate",
                                  verification_state=prior.verification, tool=step.tool, call_id=call_id,
                                  result=f"'{step.tool}' already completed in this run; duplicate skipped.",
                                  evidence=[{"type": "idempotency", "prior_step": prior_id}])
                emit(state, "ToolCompleted", {"tool": step.tool, "call_id": call_id, "status": "skipped_duplicate"})
                return out
            if prior is not None and prior.error:
                return self._outcome(step, call_id, "error", "not_executed", FailureClass.DUPLICATE_SIDE_EFFECT_RISK,
                                     f"'{step.tool}' was already attempted and may have taken effect.", t0)

        # 4. Permission + risk + learned (tighten-only) confirmation policy
        decision = self.ctx.permissions.check(tool_name=step.tool, permission_level=tool.permission_level)
        dval = str(getattr(decision, "value", decision)).lower()
        state.permission_state[step.step_id] = dval
        if dval == "denied":
            return self._outcome(step, call_id, "denied", "not_executed", FailureClass.PERMISSION_DENIED,
                                 f"Action '{step.tool}' was denied by permission policy.", t0)
        needs_confirm = dval == "needs_confirmation"
        if not needs_confirm and not toolmeta.is_read_only(step.tool, tool):
            if learned_requires_confirmation(step.tool, self.corrections_provider()):
                needs_confirm = True

        # 5. Confirmation
        if needs_confirm:
            prev = state.status
            state.transition(RunStatus.WAITING_FOR_CONFIRMATION, "ConfirmationNode", step.tool)
            self.checkpoint(state, "before_confirmation")
            try:
                prompt = self.ctx.permissions.build_confirmation_prompt(
                    tool_name=step.tool, permission_level=tool.permission_level, arguments=step.arguments)
            except Exception:
                prompt = f"Harma wants to run '{step.tool}' with {step.arguments}. Allow? (y/n)"
            approved = self._confirm(prompt)   # synchronous, matching the existing Executor contract
            state.confirmation_state[step.step_id] = "approved" if approved else "rejected"
            state.transition(prev if prev != RunStatus.WAITING_FOR_CONFIRMATION else RunStatus.EXECUTING,
                             "ConfirmationNode", "approved" if approved else "rejected")
            if not approved:
                return self._outcome(step, call_id, "cancelled", "not_executed", FailureClass.USER_CANCELLED,
                                     "Action was cancelled by the user.", t0)

        # 6. Resource lock + execute with timeout
        resource = toolmeta.resource_for(step.tool, tool)
        emit(state, "ToolStarted", {"tool": step.tool, "call_id": call_id, "step_id": step.step_id,
                                    "resource": resource})
        _publish_legacy("tool.started", {"tool": step.tool, "arguments": step.arguments})
        if state.first_action_at is None:
            state.first_action_at = time.time()
        if consequential:
            state.side_effect_fingerprints[fp] = step.step_id

        try:
            async with self.resources.acquire(resource, owner=state.run_id):
                raw = await asyncio.wait_for(self.ctx.registry.call(step.tool, **step.arguments),
                                             timeout=self.tool_timeout_s)
        except asyncio.TimeoutError:
            out = self._outcome(step, call_id, "error", "executed", FailureClass.TIMEOUT,
                                f"Tool '{step.tool}' timed out after {self.tool_timeout_s:.0f}s.", t0)
            out.error["ambiguous"] = True      # the effect may or may not have happened
            self._finish(state, out)
            return out
        except Exception as exc:
            out = self._outcome(step, call_id, "error", "executed", classify_error_text(str(exc)),
                                f"Error executing {step.tool}: {exc}", t0)
            out.error["ambiguous"] = True
            self._finish(state, out)
            return out

        # 7. Normalize
        success = bool(getattr(raw, "success", False))
        output = str(getattr(raw, "output", "") or "")
        data = getattr(raw, "data", None)
        err = str(getattr(raw, "error", "") or "")
        evidence: list[dict[str, Any]] = []
        if isinstance(data, dict) and ("evidence" in data or "verified" in data):
            evidence.append({"type": "tool_reported", "verified": data.get("verified"),
                             "detail": str(data.get("evidence", ""))[:300]})
        if success:
            vstate = VerificationState.NOT_REQUIRED if toolmeta.is_read_only(step.tool, tool) else VerificationState.PENDING
            out = ToolOutcome(status="success", action_state="executed", verification_state=vstate, tool=step.tool,
                              call_id=call_id, result=output, data=data, evidence=evidence,
                              duration_ms=round((time.perf_counter() - t0) * 1000, 2))
        else:
            fclass = classify_error_text(err or output)
            # ToolRegistry.call converts raised exceptions into "Tool 'x' crashed: …" results.
            # A crash part-way through execution is ambiguous: the effect may have happened.
            crashed = f"Tool '{step.tool}' crashed:" in err
            if consequential and not crashed:
                # The tool explicitly reported failure, so the side effect did not happen.
                state.side_effect_fingerprints.pop(fp, None)
            out = ToolOutcome(status="error", action_state="executed", verification_state=VerificationState.FAILED,
                              tool=step.tool, call_id=call_id, result=err or output, data=data, evidence=evidence,
                              error=error_payload(fclass, err or output),
                              duration_ms=round((time.perf_counter() - t0) * 1000, 2))
            if crashed:
                out.error["ambiguous"] = True
        self._finish(state, out)
        return out

    def _finish(self, state: HarmaRunState, out: ToolOutcome) -> None:
        state.tool_results.append({k: v for k, v in out.to_dict().items() if k != "data"})
        state.active_tool = ""
        emit(state, "ToolCompleted", {"tool": out.tool, "call_id": out.call_id, "status": out.status,
                                      "duration_ms": out.duration_ms})
        _publish_legacy("tool.completed", {"tool": out.tool, "success": out.ok, "output": out.result[:120]})
