"""
Harma Runtime V3 — HarmaRunner: the single authoritative run lifecycle (spec §4)

    Understand → Retrieve Experience → Choose Strategy → Execute → Observe → Verify → Learn → Reuse

HarmaRunner owns run_id, goal, state, plan, current step, strategy, tool calls, observations,
verification, recovery, learning, cancellation, pause/resume, timeouts and the result.
Subsystems (browser, computer, Android, MCP, voice, scheduled tasks) may loop internally, but
the overall task is controlled here. The LLM provides reasoning only when the ReasoningGate
says the runtime genuinely needs it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from harma.config.logging_config import get_logger
from harma.config.settings import config
from harma.core.perf import RequestTrace, Stage, record_trace
from harma.core.v3 import toolmeta
from harma.core.v3.checkpoints import CheckpointStore
from harma.core.v3.context_builder import ContextBuilder
from harma.core.v3.events import emit
from harma.core.v3.experience.analyzer import ExperienceAnalyzer
from harma.core.v3.experience.builder import ExperienceBuilder
from harma.core.v3.experience.feedback import describe as describe_feedback, infer_replaced_subject
from harma.core.v3.experience.retriever import ExperienceRetriever, RetrievedExperience
from harma.core.v3.experience.store import ExperienceStore, get_experience_store
from harma.core.v3.graph import CompletionGate, Node, ResponseComposer, enter
from harma.core.v3.intent import Intent, IntentGateway, TaskRouter
from harma.core.v3.observation import ObservationEngine
from harma.core.v3.recovery import FailureClass, RecoveryPolicy, error_payload, parse_failure
from harma.core.v3.resources import get_resource_manager
from harma.core.v3.state import (
    HarmaRunState, PlanStep, RunStatus, StepStatus, StrategyType, TaskType, VerificationState,
)
from harma.core.v3.strategy import ReasoningGate, StrategyDecision, StrategySelector
from harma.core.v3.tool_runtime import ToolOutcome, ToolRuntime
from harma.core.v3.verification import Verdict, VerificationEngine
from harma.llm.provider import Message, Role, ToolResult

log = get_logger(__name__)

_VERDICT_TO_STATE = {
    Verdict.VERIFIED: VerificationState.VERIFIED,
    Verdict.NOT_REQUIRED: VerificationState.NOT_REQUIRED,
    Verdict.FAILED: VerificationState.FAILED,
    Verdict.INCONCLUSIVE: VerificationState.UNVERIFIED,
}


class RunnerSetupError(RuntimeError):
    """Raised when V3 fails before any tool executed — the caller may safely fall back."""


@dataclass
class StepRun:
    outcome: ToolOutcome
    verdict: Verdict
    failure: Optional[FailureClass] = None
    message: str = ""


@dataclass
class ExecResult:
    status: str                                   # ok | replan | failed | cancelled | paused
    failed_step: Optional[PlanStep] = None
    failure: Optional[FailureClass] = None
    message: str = ""


@dataclass
class _RunScope:
    """Per-run, non-serialisable companions of HarmaRunState."""
    intent: Optional[Intent] = None
    experience: Optional[RetrievedExperience] = None
    decision: Optional[StrategyDecision] = None
    history: list[Message] = field(default_factory=list)
    tool_defs: Optional[list] = None
    trace: Optional[RequestTrace] = None


class HarmaRunner:
    def __init__(
        self,
        ctx: Any,
        confirm_callback: Optional[Callable[[str], str]] = None,
        experience_store: Optional[ExperienceStore] = None,
        checkpoint_dir: Optional[str] = None,
        checkpoints_enabled: bool = True,
        use_system_probes: bool = True,
        verifiers: Optional[dict] = None,
        probes: Optional[dict] = None,
        max_iterations: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
        tool_timeout_s: float = 120.0,
        analyzer_every: int = 25,
        max_replans: int = 2,
    ) -> None:
        self.ctx = ctx
        self.store = experience_store if experience_store is not None else get_experience_store()
        self.retriever = ExperienceRetriever(self.store)
        self.builder = ExperienceBuilder(self.store, registry=getattr(ctx, "registry", None))
        self.analyzer = ExperienceAnalyzer(self.store)
        self.gateway = IntentGateway(ctx.registry)
        self.router = TaskRouter(ctx.registry)
        self.selector = StrategySelector(ctx.registry, platform=sys.platform)
        self.context_builder = ContextBuilder()
        self.checkpoints = CheckpointStore(checkpoint_dir, enabled=checkpoints_enabled)
        self.tool_runtime = ToolRuntime(ctx, get_resource_manager(), confirm_callback,
                                        corrections_provider=self.store.active_corrections,
                                        checkpoint=self.checkpoints.save, tool_timeout_s=tool_timeout_s)
        self.observer = ObservationEngine(use_system_probes, probes)
        self.verifier = VerificationEngine(ctx, use_system_probes, verifiers)
        self.max_replans = max_replans
        self.recovery = RecoveryPolicy(max_retries=max(0, min(2, getattr(config.agent, "max_retries", 2))),
                                       max_replans=max_replans)
        iters = max_iterations if max_iterations is not None else config.agent.max_iterations
        self.max_llm_calls = max(1, min(iters, getattr(config.performance, "max_llm_calls", iters)))
        self.timeout_seconds = timeout_seconds or getattr(config.agent, "task_timeout_seconds", 600.0)
        self.analyzer_every = analyzer_every
        self.active_runs: dict[str, HarmaRunState] = {}
        self.paused_runs: dict[str, tuple[HarmaRunState, _RunScope]] = {}
        self.last_state: Optional[HarmaRunState] = None
        self.last_execution_meta: dict[str, Any] = {}
        self.last_learning: dict[str, Any] = {}
        self._last_run_summary: Optional[dict[str, Any]] = None
        self._completed_runs = 0
        self._analyzer_task: Optional[asyncio.Future] = None

    # ══ Public API ════════════════════════════════════════════════════════════

    async def run(self, user_input: str, request_id: Optional[str] = None) -> str:
        state = HarmaRunState(raw_request=user_input, run_id=request_id or f"run_{uuid.uuid4().hex[:10]}")
        state.deadline = state.started_at + self.timeout_seconds
        state.environment_context = {"platform": sys.platform, "runtime": "v3"}
        scope = _RunScope(trace=RequestTrace(request_id=state.run_id, user_input=user_input))
        scope.trace.mark(Stage.REQUEST_RECEIVED)
        self.active_runs[state.run_id] = state
        state.transition(RunStatus.RECEIVED, "Runner", "request received")
        emit(state, "RunCreated", {"request": user_input[:200]})

        scope.history = self._history()
        self._memory("add_user_message", user_input)
        self._memory("start_task", state.run_id[-8:], user_input)
        try:
            return await self._drive(state, scope)
        except Exception as exc:
            if state.first_action_at is None and not state.plan.steps:
                log.exception("[V3] Runner failed before any action; caller may fall back: %s", exc)
                self._rollback_user_message(user_input)
                raise RunnerSetupError(str(exc)) from exc
            log.exception("[V3] Runner error after actions started: %s", exc)
            state.last_error = error_payload(FailureClass.UNKNOWN, f"internal runtime error: {exc}")
            state.failure_classification = FailureClass.UNKNOWN.value
            return self._finish(state, scope, "failed", None)
        finally:
            self.active_runs.pop(state.run_id, None)   # paused runs live in self.paused_runs

    def pause(self, run_id: Optional[str] = None) -> list[str]:
        ids = [run_id] if run_id else list(self.active_runs)
        for rid in ids:
            if rid in self.active_runs:
                self.active_runs[rid].pause_requested = True
        return ids

    def cancel(self, run_id: Optional[str] = None) -> list[str]:
        ids = [run_id] if run_id else list(self.active_runs) + list(self.paused_runs)
        for rid in ids:
            if rid in self.active_runs:
                self.active_runs[rid].cancel_requested = True
            elif rid in self.paused_runs:
                st, sc = self.paused_runs.pop(rid)
                st.cancel_requested = True
                self._finish(st, sc, "cancelled", None)
        return ids

    async def resume(self, run_id: str) -> str:
        if run_id in self.paused_runs:
            state, scope = self.paused_runs.pop(run_id)
        else:
            state = self.checkpoints.load(run_id)
            if state is None or state.is_terminal():
                return f"No resumable run found for {run_id}."
            scope = _RunScope(trace=RequestTrace(request_id=state.run_id, user_input=state.raw_request))
        state.pause_requested = False
        state.deadline = time.time() + self.timeout_seconds
        self.active_runs[state.run_id] = state
        enter(state, Node.TOOL_EXECUTION, "resumed")
        try:
            result = await self._execute_steps(state, scope, state.plan.pending_steps())
            is_llm_task = state.strategy_type in (StrategyType.LLM_PLAN, StrategyType.LLM_RECOVERY) \
                and state.task_type not in (TaskType.CONVERSATIONAL, TaskType.RECOVERY)
            if result.status == "replan":
                return await self._run_llm(state, scope, mode="recover" if is_llm_task else "adapt", failure=result)
            if result.status == "ok" and is_llm_task:
                return await self._run_llm(state, scope, mode="resume")
            return self._conclude(state, scope, result)
        finally:
            self.active_runs.pop(state.run_id, None)

    def resumable_runs(self) -> list[dict[str, Any]]:
        mem = [{"run_id": rid, "status": "paused", "request": st.raw_request[:120], "paused": True}
               for rid, (st, _) in self.paused_runs.items()]
        known = {m["run_id"] for m in mem}
        return mem + [r for r in self.checkpoints.list_resumable() if r["run_id"] not in known]

    # ══ Driver ════════════════════════════════════════════════════════════════

    async def _drive(self, state: HarmaRunState, scope: _RunScope) -> str:
        # ── UNDERSTAND ─────────────────────────────────────────────────────────
        enter(state, Node.INTENT)
        intent = self.gateway.classify(state.raw_request, has_history=bool(scope.history))
        scope.intent = intent
        state.normalized_goal, state.task_type, state.risk_level = intent.goal, intent.task_type, intent.risk_level
        state.add_timing("classification_ms", intent.classification_ms)
        emit(state, "IntentNormalized", {"goal": intent.goal[:200]})
        emit(state, "TaskClassified", {"task_type": intent.task_type.value, "risk": intent.risk_level,
                                       "compound": intent.compound})

        if intent.task_type == TaskType.FEEDBACK:
            return self._apply_feedback(state, scope)

        # ── ROUTE (cheap; only the tools relevant to this task) ────────────────
        if intent.task_type not in (TaskType.SIMPLE_DETERMINISTIC, TaskType.CONVERSATIONAL):
            enter(state, Node.ROUTING)
            scope.trace.mark(Stage.TOOL_DISCOVERY_START)
            defs, domains, ms = self.router.route(state.raw_request)
            scope.trace.mark(Stage.TOOL_DISCOVERY_END)
            scope.trace.set_tool_counts(len(defs), len(self.ctx.registry.list_tools()))
            scope.tool_defs, state.domains = defs, domains
            state.add_timing("tool_routing_ms", ms)

        # ── RETRIEVE EXPERIENCE ────────────────────────────────────────────────
        enter(state, Node.EXPERIENCE_RETRIEVAL)
        lightweight = intent.task_type in (TaskType.SIMPLE_DETERMINISTIC, TaskType.CONVERSATIONAL)
        exp = self.retriever.retrieve(intent.goal, lightweight=lightweight)
        scope.experience = exp
        state.relevant_experiences = exp.summary()
        state.add_timing("experience_retrieval_ms", exp.duration_ms)
        emit(state, "ExperienceRetrieved", exp.summary())

        # ── SELECT STRATEGY ────────────────────────────────────────────────────
        enter(state, Node.STRATEGY_SELECTION)
        decision = self.selector.select(intent, exp)
        scope.decision = decision
        state.strategy_type, state.strategy_score, state.strategy_reason = decision.strategy, decision.score, decision.reason
        state.slot_bindings = dict(decision.bindings)
        if decision.procedure is not None:
            state.strategy_id = decision.procedure.procedure_id
            state.task_type = TaskType.KNOWN_PROCEDURE
        elif decision.strategy == StrategyType.KNOWN_WORKFLOW:
            state.task_type = TaskType.KNOWN_WORKFLOW
        state.add_timing("strategy_selection_ms", decision.duration_ms)
        emit(state, "StrategySelected", {"strategy": decision.strategy.value, "reasoning": decision.reasoning.value,
                                         "procedure_id": state.strategy_id, "score": decision.score,
                                         "reason": decision.reason, "rejected": decision.rejected[:3]})
        log.info("[V3][%s] %s → %s (%s)", state.run_id, intent.task_type.value, decision.strategy.value, decision.reason)

        if decision.strategy == StrategyType.ASK_USER:
            return self._finish(state, scope, "completed", ResponseComposer.ask_user(state))

        if decision.strategy in (StrategyType.FAST_DETERMINISTIC, StrategyType.KNOWN_PROCEDURE,
                                 StrategyType.KNOWN_WORKFLOW):
            source = {"fast_deterministic": "deterministic"}.get(decision.strategy.value, "procedure")
            steps = [PlanStep(tool=s["tool"], arguments=dict(s["arguments"]), source=source,
                              description=toolmeta.humanize_step(s["tool"], s["arguments"])) for s in decision.steps]
            state.plan.steps.extend(steps)
            state.plan.origin = source
            emit(state, "PlanCreated", {"origin": source, "steps": [s.to_dict() for s in steps]})
            self.checkpoints.save(state, "after_planning")
            result = await self._execute_steps(state, scope, steps)
            if result.status == "replan":
                return await self._run_llm(state, scope, mode="adapt", failure=result)
            return self._conclude(state, scope, result)

        # LLM_PLAN
        if intent.task_type in (TaskType.CONVERSATIONAL, TaskType.RECOVERY):
            return await self._llm_answer(state, scope)
        return await self._run_llm(state, scope, mode="plan")

    # ══ Feedback ══════════════════════════════════════════════════════════════

    def _apply_feedback(self, state: HarmaRunState, scope: _RunScope) -> str:
        enter(state, Node.STRATEGY_SELECTION, "explicit user feedback")
        state.strategy_type = StrategyType.APPLY_FEEDBACK
        corr = infer_replaced_subject(scope.intent.feedback, self._last_run_summary)
        last_proc = (self._last_run_summary or {}).get("procedure_id", "")
        if corr.kind in ("reject_last", "confirm_last"):
            proc = self.builder.apply_user_verdict(last_proc, positive=corr.kind == "confirm_last")
            if proc is not None:
                emit(state, "ExperienceUpdated", {"procedure_id": proc.procedure_id, "status": proc.status.value,
                                                  "reason": corr.kind})
        else:
            self.store.add_correction(corr)
            emit(state, "ExperienceCreated", {"correction_id": corr.correction_id, "kind": corr.kind,
                                              "subject": corr.subject, "replaces": corr.replaces})
        if corr.kind == "prefer":
            self._align_browser_preference(corr.subject)
        return self._finish(state, scope, "completed", describe_feedback(corr))

    @staticmethod
    def _align_browser_preference(subject: str) -> None:
        """Keep the existing browser controller in sync with an explicit preference (if it names a browser engine)."""
        try:
            from harma.browser.controller import get_browser_controller
            ctrl = get_browser_controller()
            engine = {"edge": "msedge", "microsoft edge": "msedge", "msedge": "msedge",
                      "chrome": "chrome", "google chrome": "chrome"}.get(subject.lower())
            if engine:
                ctrl._browser_type = engine
        except Exception:
            pass

    # ══ Step execution ════════════════════════════════════════════════════════

    def _boundary(self, state: HarmaRunState, scope: _RunScope) -> Optional[ExecResult]:
        if state.cancel_requested:
            state.transition(RunStatus.CANCELLING, "Runner", "cancel requested")
            return ExecResult("cancelled")
        if state.pause_requested:
            state.transition(RunStatus.PAUSED, "Runner", "pause requested")
            self.checkpoints.save(state, "before_pause")
            emit(state, "RunPaused", {"pending": len(state.plan.pending_steps())})
            self.paused_runs[state.run_id] = (state, scope)
            return ExecResult("paused")
        if state.deadline and time.time() > state.deadline:
            state.last_error = error_payload(FailureClass.TIMEOUT, "task deadline exceeded")
            state.failure_classification = FailureClass.TIMEOUT.value
            return ExecResult("failed", failure=FailureClass.TIMEOUT, message="task deadline exceeded")
        return None

    def _parallel_safe(self, step: PlanStep) -> bool:
        tool = self.ctx.registry.get(step.tool)
        return tool is not None and toolmeta.is_read_only(step.tool, tool) and toolmeta.resource_for(step.tool, tool) is None

    async def _execute_steps(self, state: HarmaRunState, scope: _RunScope, steps: list[PlanStep]) -> ExecResult:
        trace = scope.trace
        if trace and Stage.TOOL_EXECUTION_START.value not in getattr(trace, "_marks", {}):
            trace.mark(Stage.TOOL_EXECUTION_START)
        i = 0
        try:
            while i < len(steps):
                step = steps[i]
                if step.status != StepStatus.PENDING:
                    i += 1
                    continue
                stop = self._boundary(state, scope)
                if stop is not None:
                    return stop

                group = [step]
                if self._parallel_safe(step):
                    j = i + 1
                    while j < len(steps) and steps[j].status == StepStatus.PENDING and self._parallel_safe(steps[j]):
                        group.append(steps[j])
                        j += 1
                state.current_step = step.step_id
                if len(group) > 1:
                    runs = await asyncio.gather(*(self._run_step(state, s, scope) for s in group))
                else:
                    runs = [await self._run_step(state, step, scope)]

                retry_from: Optional[int] = None
                for k, (s, r) in enumerate(zip(group, runs)):
                    if r.failure is None:
                        continue
                    res = await self._recover(state, s, r)
                    if res == "retry":
                        retry_from = i + k
                        break
                    if res == "replan":
                        for rest in steps[i + k + 1:]:
                            if rest.status == StepStatus.PENDING:
                                rest.status = StepStatus.SKIPPED
                        return ExecResult("replan", s, r.failure, r.message)
                    return ExecResult("failed", s, r.failure, r.message)
                if retry_from is not None:
                    i = retry_from
                    continue
                i += len(group)
            return ExecResult("ok")
        finally:
            if trace:
                trace.mark(Stage.TOOL_EXECUTION_END)
            state.update_progress()

    async def _run_step(self, state: HarmaRunState, step: PlanStep, scope: _RunScope) -> StepRun:
        enter(state, Node.TOOL_EXECUTION, step.tool)
        step.status = StepStatus.RUNNING
        t0 = time.perf_counter()
        outcome = await self.tool_runtime.execute(state, step)
        state.add_timing("tool_execution_ms", (time.perf_counter() - t0) * 1000)
        step.duration_ms += outcome.duration_ms
        if scope.trace:
            scope.trace.record_tool_call()
            if step.tool in ("take_screenshot", "observe_screen", "android.screenshot"):
                scope.trace.record_screenshot()

        if not outcome.ok:
            step.status = StepStatus.FAILED
            step.verification = VerificationState.FAILED
            step.error = dict(outcome.error or {}, executed=outcome.action_state == "executed")
            step.result_summary = outcome.result[:300]
            failure = parse_failure((outcome.error or {}).get("type"))
            state.last_error = dict(step.error, tool=step.tool)
            return StepRun(outcome, Verdict.FAILED, failure, outcome.result)

        # ── OBSERVE ──
        enter(state, Node.OBSERVATION, step.tool)
        t1 = time.perf_counter()
        obs = await self.observer.observe(state, step, outcome)
        state.add_timing("observation_ms", (time.perf_counter() - t1) * 1000)
        emit(state, "ObservationCreated", {"step_id": step.step_id, "level": obs.get("level"),
                                           "fingerprint": obs.get("fingerprint")})

        # ── VERIFY ──
        enter(state, Node.VERIFICATION, step.tool)
        t2 = time.perf_counter()
        verdict, detail, evidence = await self.verifier.verify(step, outcome, obs)
        if verdict == Verdict.INCONCLUSIVE:          # one re-observation, then UNVERIFIED
            enter(state, Node.OBSERVATION, "re-observe")
            obs = await self.observer.observe(state, step, outcome)
            enter(state, Node.VERIFICATION, "re-verify")
            verdict, detail, evidence = await self.verifier.verify(step, outcome, obs)
        state.add_timing("verification_ms", (time.perf_counter() - t2) * 1000)
        step.verification = _VERDICT_TO_STATE[verdict]
        step.result_summary = outcome.result[:300]
        state.evidence.extend((evidence + outcome.evidence)[:5])
        if len(state.evidence) > 60:
            del state.evidence[:-60]
        emit(state, "VerificationCompleted", {"step_id": step.step_id, "tool": step.tool,
                                              "verdict": step.verification.value, "detail": detail[:200]})

        # ── LOOP DETECTION (action + state + result) ──
        fp = hashlib.sha1(json.dumps([step.tool, step.arguments, obs.get("fingerprint"), outcome.status,
                                      outcome.result[:80]], sort_keys=True, default=str).encode()).hexdigest()[:16]
        if state.record_loop_fingerprint(fp):
            step.status = StepStatus.FAILED
            step.error = error_payload(FailureClass.LOOP_DETECTED, f"repeated {step.tool} without progress", executed=True)
            state.last_error = dict(step.error, tool=step.tool)
            state.working_memory["loops"] = state.working_memory.get("loops", 0) + 1
            return StepRun(outcome, verdict, FailureClass.LOOP_DETECTED, step.error["message"])

        if verdict == Verdict.FAILED:
            step.status = StepStatus.FAILED
            step.error = error_payload(FailureClass.VERIFICATION_FAILED, detail, executed=True)
            state.last_error = dict(step.error, tool=step.tool)
            return StepRun(outcome, verdict, FailureClass.VERIFICATION_FAILED, detail)

        step.status = StepStatus.SUCCEEDED
        if not toolmeta.is_read_only(step.tool):
            self.checkpoints.save(state, "after_side_effect")
            app = next((v for k, v in step.arguments.items() if "application" in k and isinstance(v, str)), None)
            if app and step.verification == VerificationState.VERIFIED:
                try:
                    self.ctx.memory.active_application = app
                except Exception:
                    pass
        self._resolve_superseded(state)
        return StepRun(outcome, verdict, None, detail)

    def _resolve_superseded(self, state: HarmaRunState) -> None:
        pending_fail = state.working_memory.get("unresolved_failure")
        if not pending_fail:
            return
        for s in state.plan.steps:
            if s.step_id == pending_fail and s.error is not None:
                s.error["superseded"] = True
        state.working_memory["unresolved_failure"] = None

    async def _recover(self, state: HarmaRunState, step: PlanStep, run: StepRun) -> str:
        enter(state, Node.RECOVERY, run.failure.value if run.failure else "")
        t0 = time.perf_counter()
        tool = self.ctx.registry.get(step.tool)
        failure = run.failure or FailureClass.UNKNOWN
        if failure == FailureClass.LOOP_DETECTED and state.working_memory.get("loops", 0) >= 2:
            decision_action, reason = "fail", "repeated loop"
        else:
            d = self.recovery.decide(
                failure=failure, step_attempts=step.attempts, replan_count=state.replan_count,
                consequential=toolmeta.is_consequential(step.tool, tool),
                action_executed=bool((step.error or {}).get("executed")),
                ambiguous=bool((step.error or {}).get("ambiguous")), message=run.message,
            )
            decision_action, reason = d.action, d.reason
            if d.failure != failure:
                failure = d.failure
                step.error = dict(step.error or {}, type=failure.value)
            if d.action == "retry":
                state.retry_count += 1
                if d.backoff_s:
                    await asyncio.sleep(d.backoff_s)
        state.recovery_count += 1
        state.failure_classification = failure.value
        state.add_timing("recovery_ms", (time.perf_counter() - t0) * 1000)
        gate = ReasoningGate.for_failure(state.strategy_type, decision_action)
        emit(state, "RecoveryStarted", {"step_id": step.step_id, "tool": step.tool, "failure": failure.value,
                                        "action": decision_action, "reasoning": gate.value, "reason": reason[:200]})
        if decision_action == "retry":
            step.status = StepStatus.PENDING
            return "retry"
        if decision_action == "replan":
            state.working_memory["unresolved_failure"] = step.step_id
            self.checkpoints.save(state, "after_recovery")
            return "replan"
        state.last_error = dict(step.error or {}, tool=step.tool, type=failure.value)
        return "fail"

    # ══ LLM reasoning ═════════════════════════════════════════════════════════

    async def _call_llm(self, state: HarmaRunState, scope: _RunScope, messages: list[Message],
                        tools: Optional[list], purpose: str):
        trace = scope.trace
        first = state.llm_calls == 0
        if trace:
            trace.mark(Stage.LLM_REQUEST_START if first else Stage.LLM_CONTINUATION_START)
        t0 = time.perf_counter()
        resp = await self.ctx.llm.complete(messages=messages, tools=tools or None,
                                           system=self.context_builder.system_prompt())
        ms = (time.perf_counter() - t0) * 1000
        if trace:
            trace.mark(Stage.LLM_REQUEST_END if first else Stage.LLM_CONTINUATION_END)
        usage = getattr(resp, "usage", None) or {}
        tin, tout = int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0)
        state.llm_calls += 1
        state.tokens_in += tin
        state.tokens_out += tout
        state.add_timing("llm_ms", ms)
        if purpose in ("plan", "adapt", "recover", "resume"):
            state.add_timing("planning_ms", ms)
        if trace:
            trace.record_llm_call(tokens_in=tin, tokens_out=tout)
        return resp

    def _runtime_context(self, state: HarmaRunState, scope: _RunScope) -> dict[str, Any]:
        exp_ctx = scope.experience.to_untrusted_context() if scope.experience else {}
        memory_ctx = ""
        ltm = getattr(self.ctx, "long_term_memory", None)
        if ltm is not None and getattr(ltm, "is_available", False) \
                and state.task_type not in (TaskType.CONVERSATIONAL, TaskType.SIMPLE_DETERMINISTIC):
            t0 = time.perf_counter()
            if scope.trace:
                scope.trace.mark(Stage.MEMORY_RETRIEVAL_START)
            try:
                memory_ctx = ltm.build_context(state.raw_request) or ""
            except Exception as exc:
                log.debug("[V3] LTM context error: %s", exc)
            if scope.trace:
                scope.trace.mark(Stage.MEMORY_RETRIEVAL_END)
            state.add_timing("memory_retrieval_ms", (time.perf_counter() - t0) * 1000)
        return self.context_builder.build_runtime_context(experience=exp_ctx, memory_context=memory_ctx)

    def _adaptation_payload(self, state: HarmaRunState, scope: _RunScope, failure: Optional[ExecResult]) -> dict[str, Any]:
        steps = state.plan.steps
        payload: dict[str, Any] = {
            "completed_steps": [{"tool": s.tool, "arguments": s.arguments, "result": s.result_summary[:200],
                                 "verification": s.verification.value}
                                for s in steps if s.status == StepStatus.SUCCEEDED],
        }
        if failure is not None and failure.failed_step is not None:
            fs = failure.failed_step
            payload["failed_step"] = {"tool": fs.tool, "arguments": fs.arguments,
                                      "failure_type": failure.failure.value if failure.failure else "unknown",
                                      "error": (failure.message or "")[:300]}
        skipped = [{"tool": s.tool, "arguments": s.arguments} for s in steps if s.status == StepStatus.SKIPPED]
        if skipped:
            payload["remaining_planned_steps"] = skipped
        if state.observations:
            last = state.observations[-1]
            payload["current_observation"] = {k: v for k, v in last.items()
                                              if k in ("active_window", "app", "current_url", "page_title", "tool_output")}
        proc = scope.decision.procedure if scope.decision else None
        if proc is not None:
            payload["known_procedure"] = {"steps": proc.steps, "confidence": proc.confidence,
                                          "status": proc.status.value, "source": proc.source}
        if scope.experience:
            exp_ctx = scope.experience.to_untrusted_context()
            for k in ("failure_lessons", "user_preferences"):
                if k in exp_ctx:
                    payload[k] = exp_ctx[k]
        return payload

    def _tool_result_message(self, steps: list[PlanStep], calls: list) -> Message:
        by_id = {s.llm_call_id: s for s in steps}
        results = []
        for tc in calls:
            s = by_id.get(tc.id)
            if s is None or s.status in (StepStatus.PENDING, StepStatus.SKIPPED):
                content, is_err = json.dumps({"skipped": "not executed (an earlier step failed or the run paused)"}), True
            elif s.status == StepStatus.SUCCEEDED:
                content = s.result_summary or "ok"
                if s.verification == VerificationState.UNVERIFIED:
                    content += "\n[runtime: action dispatched; effect not independently verified]"
                elif s.verification == VerificationState.VERIFIED:
                    content += "\n[runtime: effect verified]"
                is_err = False
            else:
                content, is_err = json.dumps({"error": (s.error or {}).get("message", "failed"),
                                              "failure_type": (s.error or {}).get("type", "unknown")}), True
            results.append(ToolResult(tool_call_id=tc.id, name=tc.name, content=content, is_error=is_err))
        return Message(role=Role.TOOL, tool_results=results)

    def _can_complete_deterministically(self, state: HarmaRunState, scope: _RunScope, batch: list[PlanStep]) -> bool:
        intent = scope.intent
        if intent is None or intent.compound or len(batch) != 1 or len(state.plan.steps) != 1:
            return False
        s = batch[0]
        if s.status != StepStatus.SUCCEEDED:
            return False
        if s.tool in toolmeta.SELF_DESCRIBING:
            return True
        return s.verification == VerificationState.VERIFIED and not toolmeta.is_read_only(s.tool)

    async def _run_llm(self, state: HarmaRunState, scope: _RunScope, mode: str,
                       failure: Optional[ExecResult] = None) -> str:
        """LLM_PLAN / adaptation / recovery / resume loop. Returns the final response."""
        enter(state, Node.PLANNING if mode == "plan" else Node.REPLANNING, mode)
        if mode != "plan":
            state.replan_count += 1 if mode in ("adapt", "recover") else 0
        if mode in ("adapt", "recover") and state.strategy_type == StrategyType.FAST_DETERMINISTIC:
            state.strategy_type = StrategyType.LLM_RECOVERY
            state.strategy_reason = "deterministic action failed; LLM recovery"
            emit(state, "StrategySelected", {"strategy": state.strategy_type.value, "reasoning": "recover",
                                             "reason": state.strategy_reason})
        if scope.tool_defs is None:
            extra = [s.tool for s in state.plan.steps]
            scope.tool_defs, state.domains, ms = self.router.route(state.raw_request, extra_tools=extra)
            state.add_timing("tool_routing_ms", ms)
        else:
            extra = [s.tool for s in state.plan.steps if s.tool not in {d.name for d in scope.tool_defs}]
            if extra:
                scope.tool_defs, _, _ = self.router.route(state.raw_request, extra_tools=extra + [d.name for d in scope.tool_defs])

        messages: Optional[list[Message]] = state.working_memory.get("messages")
        if mode == "plan" or messages is None:
            if mode == "plan":
                messages = self.context_builder.initial_messages(state.raw_request, scope.history,
                                                                 self._runtime_context(state, scope))
            else:
                messages = [self.context_builder.adaptation_message(
                    state.raw_request, self._adaptation_payload(state, scope, failure), mode)]
        else:
            messages.append(self.context_builder.adaptation_message(
                state.raw_request, self._adaptation_payload(state, scope, failure), mode))
        state.working_memory["messages"] = messages
        purpose = mode

        while True:
            stop = self._boundary(state, scope)
            if stop is not None:
                return self._conclude(state, scope, stop)
            if state.llm_calls >= self.max_llm_calls:
                log.info("[V3][%s] LLM budget reached (%d)", state.run_id, state.llm_calls)
                return self._conclude(state, scope, ExecResult("ok"), budget_exhausted=True)
            try:
                resp = await self._call_llm(state, scope, messages, scope.tool_defs, purpose)
            except Exception as exc:
                log.warning("[V3][%s] LLM call failed: %s", state.run_id, exc)
                state.last_error = error_payload(FailureClass.TRANSIENT, f"language model unavailable: {exc}")
                state.failure_classification = FailureClass.TRANSIENT.value
                return self._finish(state, scope, "failed", None)
            purpose = "continue"

            if not resp.tool_calls:
                text = (resp.content or "").strip()
                return self._conclude(state, scope, ExecResult("ok"), llm_text=text)

            messages.append(Message(role=Role.ASSISTANT, content=resp.content or "", tool_calls=resp.tool_calls))
            batch = [PlanStep(tool=tc.name, arguments=dict(tc.arguments or {}), llm_call_id=tc.id,
                              source="llm" if mode == "plan" else "recovery",
                              description=toolmeta.humanize_step(tc.name, tc.arguments or {}))
                     for tc in resp.tool_calls]
            if not state.plan.steps:
                state.plan.origin = "llm"
            state.plan.steps.extend(batch)
            emit(state, "PlanCreated" if mode == "plan" and state.replan_count == 0 else "ReplanCreated",
                 {"steps": [s.to_dict() for s in batch], "llm_call": state.llm_calls})
            self.checkpoints.save(state, "after_planning")

            result = await self._execute_steps(state, scope, batch)
            messages.append(self._tool_result_message(batch, resp.tool_calls))

            if result.status in ("cancelled", "paused", "failed"):
                return self._conclude(state, scope, result)
            if result.status == "replan":
                state.replan_count += 1
                enter(state, Node.REPLANNING, result.failure.value if result.failure else "")
                messages.append(self.context_builder.adaptation_message(
                    state.raw_request, self._adaptation_payload(state, scope, result), "recover"))
                continue
            if mode == "plan" and self._can_complete_deterministically(state, scope, batch):
                return self._conclude(state, scope, ExecResult("ok"))

    async def _llm_answer(self, state: HarmaRunState, scope: _RunScope) -> str:
        """Conversational or explanation requests: one LLM call, no tools."""
        enter(state, Node.PLANNING, state.task_type.value)
        rc: dict[str, Any] = {}
        if state.task_type == TaskType.RECOVERY and self._last_run_summary:
            rc["previous_run"] = self._last_run_summary
        messages = self.context_builder.initial_messages(state.raw_request, scope.history, rc)
        try:
            resp = await self._call_llm(state, scope, messages, None, "answer")
            text = (resp.content or "").strip()
        except Exception as exc:
            log.warning("[V3] LLM answer failed: %s", exc)
            if state.task_type == TaskType.RECOVERY and self._last_run_summary:
                text = f"The previous run ended with: {self._last_run_summary.get('error') or self._last_run_summary.get('outcome')}."
            else:
                state.last_error = error_payload(FailureClass.TRANSIENT, f"language model unavailable: {exc}")
                state.failure_classification = FailureClass.TRANSIENT.value
                return self._finish(state, scope, "failed", None)
        if not text and state.task_type == TaskType.RECOVERY and self._last_run_summary:
            text = f"The previous run ended with: {self._last_run_summary.get('error') or self._last_run_summary.get('outcome')}."
        return self._finish(state, scope, "completed", text or "I'm here — how can I help?")

    # ══ Conclusion ════════════════════════════════════════════════════════════

    def _conclude(self, state: HarmaRunState, scope: _RunScope, result: ExecResult,
                  llm_text: str = "", budget_exhausted: bool = False) -> str:
        if result.status == "paused":
            return ResponseComposer.paused(state)
        if result.status == "cancelled":
            return self._finish(state, scope, "cancelled", None)
        if result.status == "failed":
            if result.failure and not state.failure_classification:
                state.failure_classification = result.failure.value
            return self._finish(state, scope, "failed", llm_text or None)

        ok, outcome, reason = CompletionGate.evaluate(state)
        if not ok:
            if budget_exhausted:
                state.last_error = state.last_error or error_payload(FailureClass.UNKNOWN, "reasoning step budget reached")
            state.failure_classification = state.failure_classification or FailureClass.UNKNOWN.value
            if not state.last_error:
                state.last_error = error_payload(FailureClass.UNKNOWN, reason)
            return self._finish(state, scope, "failed", llm_text or None)
        state.final_outcome = outcome
        if budget_exhausted and not llm_text and not any(s.status == StepStatus.SUCCEEDED for s in state.plan.steps):
            state.last_error = error_payload(FailureClass.UNKNOWN, "reasoning step budget reached")
            state.failure_classification = FailureClass.UNKNOWN.value
            return self._finish(state, scope, "failed", None)
        response = llm_text or ResponseComposer.completed(state)
        if llm_text and outcome == "unverified" and any(
                s.verification == VerificationState.UNVERIFIED and not toolmeta.is_read_only(s.tool)
                for s in state.plan.steps if s.status == StepStatus.SUCCEEDED):
            response += "\n\n(Note: I couldn't independently verify every step.)"
        return self._finish(state, scope, "completed", response)

    def _finish(self, state: HarmaRunState, scope: _RunScope, status: str, response: Optional[str]) -> str:
        trace = scope.trace
        if status == "failed":
            state.final_outcome = "failed"
            response = response or ResponseComposer.failed(state)
        elif status == "cancelled":
            state.final_outcome = "cancelled"
            response = response or ResponseComposer.cancelled(state)
        elif not state.final_outcome:
            state.final_outcome = "answered"
        response = response or "Done."

        # ── LEARN (verified-only reinforcement; never blocks on errors) ──
        if state.plan.steps and state.strategy_type != StrategyType.APPLY_FEEDBACK:
            enter(state, Node.LEARNING)
            t0 = time.perf_counter()
            self.last_learning = self.builder.learn(state)
            state.add_timing("learning_ms", (time.perf_counter() - t0) * 1000)
        else:
            self.last_learning = {"action": "none"}

        terminal = {"completed": RunStatus.COMPLETED, "failed": RunStatus.FAILED,
                    "cancelled": RunStatus.CANCELLED}[status]
        if status == "completed":
            enter(state, Node.COMPLETION, state.final_outcome)
        elif status == "failed":
            enter(state, Node.FAILURE, state.failure_classification)
        else:
            state.transition(terminal, "Runner", "cancelled")
        state.result = response
        if state.first_action_at:
            state.timings_ms["first_action_latency_ms"] = round((state.first_action_at - state.started_at) * 1000, 2)
        state.timings_ms["total_ms"] = round(state.elapsed_ms(), 2)
        event = {"completed": "RunCompleted", "failed": "RunFailed", "cancelled": "RunCancelled"}[status]
        emit(state, event, {"outcome": state.final_outcome, "llm_calls": state.llm_calls,
                            "tool_calls": len(state.tool_results), "total_ms": state.timings_ms["total_ms"],
                            "learning": self.last_learning.get("action")},
             severity="error" if status == "failed" else "info")
        self.checkpoints.save(state, "after_completion")

        # ── Memory sync (same contract as the existing engine) ──
        self._memory("add_assistant_message", response)
        self._memory("complete_task", response)
        ltm = getattr(self.ctx, "long_term_memory", None)
        if ltm is not None and getattr(ltm, "is_available", False) and state.task_type not in (
                TaskType.CONVERSATIONAL, TaskType.FEEDBACK):
            try:
                ltm.extract_and_save(state.raw_request)
            except Exception as exc:
                log.debug("[V3] memory extraction error: %s", exc)

        # ── Meta for API / Control Center ──
        if trace is not None:
            trace.mark(Stage.API_RESPONSE)
            try:
                trace.log_trace()
                record_trace(trace)
            except Exception:
                pass
        self.last_state = state
        self.last_execution_meta = {
            "request_id": state.run_id,
            "status": status,
            "response": response,
            "plan_id": None,
            "tool_calls": [{"tool": r["tool"], "status": "success" if r["status"] == "success" else "error",
                            "error": r.get("error")} for r in state.tool_results],
            "verification": {"status": state.final_outcome,
                             "steps": [{"tool": s.tool, "verification": s.verification.value} for s in state.plan.steps]},
            "trace": f"Harma Runtime V3 run for {state.raw_request[:80]}",
            "execution_context": state.summary(),
            "perf": trace.summary() if trace is not None else {},
            "v3": {**state.summary(), "strategy_reason": state.strategy_reason, "learning": self.last_learning,
                   "experience": state.relevant_experiences},
        }
        self._last_run_summary = {
            "run_id": state.run_id, "outcome": state.final_outcome,
            "procedure_id": self.last_learning.get("procedure_id") or state.strategy_id,
            "steps": [{"tool": s.tool, "arguments": s.arguments, "status": s.status.value} for s in state.plan.steps],
            "error": (state.last_error or {}).get("message", "") if status == "failed" else "",
        }
        log.info("[V3][%s] %s outcome=%s strategy=%s llm=%d tools=%d total=%.0fms",
                 state.run_id, status.upper(), state.final_outcome,
                 state.strategy_type.value if state.strategy_type else "-", state.llm_calls,
                 len(state.tool_results), state.timings_ms["total_ms"])
        self._maybe_analyze()
        return response

    # ══ Helpers ═══════════════════════════════════════════════════════════════

    def _history(self) -> list[Message]:
        try:
            return self.context_builder.conversation_tail(self.ctx.memory.get_messages())
        except Exception:
            return []

    def _rollback_user_message(self, user_input: str) -> None:
        """Undo our memory write so a fallback runtime does not record the request twice."""
        msgs = getattr(getattr(self.ctx, "memory", None), "_messages", None)
        try:
            if msgs and msgs[-1].role == Role.USER and msgs[-1].content == user_input:
                msgs.pop()
        except Exception:
            pass

    def _memory(self, method: str, *args: Any) -> None:
        mem = getattr(self.ctx, "memory", None)
        fn = getattr(mem, method, None)
        if fn is None:
            return
        try:
            fn(*args)
        except Exception as exc:
            log.debug("[V3] memory.%s failed: %s", method, exc)

    def _maybe_analyze(self) -> None:
        """Background experience analysis — never on the synchronous task path."""
        self._completed_runs += 1
        if self.analyzer_every <= 0 or self._completed_runs % self.analyzer_every:
            return
        if self._analyzer_task is not None and not self._analyzer_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
            self._analyzer_task = loop.run_in_executor(None, self.analyzer.analyze)
        except RuntimeError:
            pass
