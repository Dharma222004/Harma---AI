"""
Harma Runtime V3 — Experience Builder (spec §10–12, §41–42)

Transforms a finished run into structured experience — never a raw transcript:

    Execution → Evidence → Verification → Outcome → Extraction → Evaluation → Memory

Hard rules enforced here:
  * Only VERIFIED runs reinforce (or create trusted-track) procedures.
  * Unverified runs are recorded as unverified experience and never reinforce.
  * Failed runs create failure experience and demote the procedure that was used.
  * Arguments containing secrets are redacted and never become procedures.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from harma.config.logging_config import get_logger
from harma.core.v3.events import emit
from harma.core.v3.experience import templates as tpl
from harma.core.v3.experience.models import (
    Episode, ExperienceSource, FailureExperience, Procedure, ProcedureStatus, SemanticFact, refresh,
)
from harma.core.v3.experience.store import ExperienceStore
from harma.core.v3.state import HarmaRunState, StepStatus, StrategyType, VerificationState
from harma.core.v3 import toolmeta

log = get_logger(__name__)

LESSONS: dict[str, str] = {
    "element_not_found": "verify the target window/element exists and is ready before interacting with it",
    "timeout": "wait for the expected state (condition-based wait) before the next step",
    "environment_changed": "re-observe the current state before continuing",
    "invalid_argument": "validate arguments against the tool schema before calling",
    "permission_denied": "this action needs explicit permission; ask the user first",
    "authentication": "credentials are required; ask the user to sign in",
    "user_cancelled": "the user declined this action; ask before attempting it again",
    "verification_failed": "the action ran but the goal state was not reached; observe and verify before moving on",
    "loop_detected": "do not repeat the same action when the state does not change; try an alternative",
    "transient": "transient error; a bounded retry is usually sufficient",
    "resource_unavailable": "the required device/display/session was unavailable; check it first",
    "duplicate_side_effect_risk": "a consequential action may already have happened; verify before repeating",
}

_APP_ARG_HINTS = ("application", "app_name", "app", "package", "program")


def _redact_args(args: dict[str, Any], detector: Any) -> tuple[dict[str, Any], bool]:
    found = False
    out: dict[str, Any] = {}
    for k, v in (args or {}).items():
        if isinstance(v, str) and detector is not None:
            try:
                if detector.contains_secret(v):
                    out[k] = "[REDACTED]"
                    found = True
                    continue
            except Exception:
                pass
        if isinstance(v, str) and len(v) > 300:
            v = v[:300] + "..."
        out[k] = v
    return out, found


def _running_mean(old: float, n_old: int, new: float) -> float:
    return round((old * n_old + new) / (n_old + 1), 2) if n_old >= 0 else new


class ExperienceBuilder:
    def __init__(self, store: ExperienceStore, registry: Any = None) -> None:
        self.store = store
        self.registry = registry
        try:
            from harma.memory.privacy import SecretDetector
            self._detector = SecretDetector()
        except Exception:
            self._detector = None

    # ── Public ────────────────────────────────────────────────────────────────

    def learn(self, state: HarmaRunState) -> dict[str, Any]:
        """Extract, evaluate and persist experience for a terminal run. Never raises."""
        report: dict[str, Any] = {"action": "none"}
        try:
            report = self._learn(state)
        except Exception as exc:
            log.warning("[V3][LEARN] Experience extraction failed: %s", exc)
            report = {"action": "error", "error": str(exc)}
        return report

    # ── Internals ─────────────────────────────────────────────────────────────

    def _tool(self, name: str) -> Any:
        try:
            return self.registry.get(name) if self.registry is not None else None
        except Exception:
            return None

    def _learn(self, state: HarmaRunState) -> dict[str, Any]:
        steps = state.plan.steps
        if not steps:
            return {"action": "none"}

        duplicates = set(state.working_memory.get("duplicate_steps", []))
        executed = [s for s in steps if s.status == StepStatus.SUCCEEDED and s.step_id not in duplicates]
        any_secret = False
        ep_steps = []
        for s in steps:
            red, secret = _redact_args(s.arguments, self._detector)
            any_secret = any_secret or secret
            ep_steps.append({"tool": s.tool, "args": red, "status": s.status.value,
                             "verification": s.verification.value, "duration_ms": round(s.duration_ms, 1),
                             "source": s.source})
        errors = [s.error for s in steps if s.error]

        outcome = state.final_outcome
        episode = Episode(
            run_id=state.run_id, goal=state.normalized_goal[:300], task_type=state.task_type.value,
            strategy=state.strategy_type.value if state.strategy_type else "",
            template="", procedure_id=state.strategy_id, steps=ep_steps, errors=errors[:5],
            outcome=outcome, duration_ms=round(state.elapsed_ms(), 1), llm_calls=state.llm_calls,
            tool_calls=sum(max(1, s.attempts) for s in steps if s.attempts),
            environment=dict(state.environment_context),
        )
        report: dict[str, Any] = {"action": "episode", "episode_id": episode.episode_id}

        used_proc: Optional[Procedure] = self.store.get_procedure(state.strategy_id) if state.strategy_id else None

        if outcome == "verified" and executed:
            report.update(self._learn_success(state, executed, used_proc, any_secret, episode))
            self._record_recovered_lessons(state, report.get("procedure_id", ""), episode.template)
            self._record_facts(state, executed)
        elif outcome == "unverified":
            report.update(self._learn_unverified(state, executed, used_proc, any_secret, episode))
        elif outcome == "failed":
            report.update(self._learn_failure(state, used_proc))
        self.store.add_episode(episode)
        return report

    def _learn_success(self, state, executed, used_proc, any_secret, episode) -> dict[str, Any]:
        if any_secret:
            return {"action": "skipped_secret"}
        if state.strategy_type == StrategyType.FAST_DETERMINISTIC:
            return {"action": "fast_path_no_procedure"}   # already zero-LLM; nothing to learn procedurally

        raw_steps = [{"tool": s.tool, "arguments": dict(s.arguments)} for s in executed]
        built = tpl.build_template(state.raw_request, raw_steps)
        if built is None:
            norm = tpl.normalize_request(state.raw_request).lower()
            if "{" in norm or "}" in norm or not norm:
                return {"action": "not_generalizable"}
            built = {"template": norm, "slots": [], "steps": raw_steps, "bindings": {}}
        episode.template = built["template"]
        key = tpl.procedure_key(built["steps"])
        now = time.time()

        adapted = used_proc is not None and tpl.procedure_key(used_proc.steps) != key
        proc = self.store.get_procedure_by_key(key)
        created = proc is None
        if created:
            proc = Procedure(task_pattern=tpl.task_pattern(built["steps"]), steps=built["steps"],
                             templates=[built["template"]], slots=built["slots"],
                             source=ExperienceSource.VERIFIED_EXECUTION.value)
        elif built["template"] not in proc.templates:
            proc.templates.append(built["template"])

        n_prev = proc.success_count
        proc.success_count += 1
        proc.usage_count += 1
        proc.consecutive_failures = 0
        proc.last_success_at = now
        proc.last_used_at = now
        proc.avg_latency_ms = _running_mean(proc.avg_latency_ms, n_prev, state.elapsed_ms())
        proc.avg_llm_calls = _running_mean(proc.avg_llm_calls, n_prev, float(state.llm_calls))
        proc.avg_tool_calls = _running_mean(proc.avg_tool_calls, n_prev, float(len(executed)))
        proc.capabilities = sorted({toolmeta.domain_of(s.tool) for s in executed})
        proc.risk_level = toolmeta.max_risk([toolmeta.risk_of(s.tool, self._tool(s.tool)) for s in executed])
        proc.verification_strategy = [f"{s.tool}:{s.verification.value}" for s in executed]
        proc.success_criteria = [s.result_summary[:120] for s in executed
                                 if s.verification == VerificationState.VERIFIED and s.result_summary][:5]
        proc.environment = {k: v for k, v in state.environment_context.items() if k in ("platform", "runtime")}
        proc.preconditions = {"tools": sorted({s.tool for s in executed})}
        refresh(proc, now)
        self.store.upsert_procedure(proc, key)
        emit(state, "ExperienceCreated" if created else "ExperienceUpdated", {
            "procedure_id": proc.procedure_id, "status": proc.status.value,
            "confidence": proc.confidence, "template": built["template"],
        })

        if adapted and used_proc is not None:
            # The reused procedure did not work as-is: record the mismatch without poisoning it.
            used_proc.failure_count += 1
            used_proc.consecutive_failures += 1
            used_proc.usage_count += 1
            used_proc.last_used_at = now
            used_proc.known_failure_modes = (used_proc.known_failure_modes + [{
                "failure": state.failure_classification or "procedure_mismatch",
                "adapted_to": proc.procedure_id, "t": now,
            }])[-5:]
            refresh(used_proc, now)
            self.store.upsert_procedure(used_proc, tpl.procedure_key(used_proc.steps))
            emit(state, "ExperienceUpdated", {"procedure_id": used_proc.procedure_id,
                                              "status": used_proc.status.value, "reason": "adapted"})
        episode.procedure_id = proc.procedure_id
        return {"action": "created" if created else "reinforced", "procedure_id": proc.procedure_id,
                "status": proc.status.value, "confidence": proc.confidence, "template": built["template"],
                "adapted_from": used_proc.procedure_id if adapted and used_proc else ""}

    def _learn_unverified(self, state, executed, used_proc, any_secret, episode) -> dict[str, Any]:
        now = time.time()
        if used_proc is not None:
            used_proc.unverified_count += 1
            used_proc.usage_count += 1
            used_proc.last_used_at = now
            refresh(used_proc, now)
            self.store.upsert_procedure(used_proc, tpl.procedure_key(used_proc.steps))
            return {"action": "unverified_reuse", "procedure_id": used_proc.procedure_id}
        if any_secret or not executed or state.strategy_type == StrategyType.FAST_DETERMINISTIC:
            return {"action": "unverified"}
        raw_steps = [{"tool": s.tool, "arguments": dict(s.arguments)} for s in executed]
        built = tpl.build_template(state.raw_request, raw_steps)
        if built is None:
            return {"action": "unverified"}
        episode.template = built["template"]
        key = tpl.procedure_key(built["steps"])
        proc = self.store.get_procedure_by_key(key)
        if proc is None:
            proc = Procedure(task_pattern=tpl.task_pattern(built["steps"]), steps=built["steps"],
                             templates=[built["template"]], slots=built["slots"],
                             source=ExperienceSource.UNVERIFIED_EXECUTION.value)
        proc.unverified_count += 1
        proc.usage_count += 1
        proc.last_used_at = now
        refresh(proc, now)   # success_count == 0 → stays UNVERIFIED; never reused directly
        self.store.upsert_procedure(proc, key)
        return {"action": "unverified", "procedure_id": proc.procedure_id, "status": proc.status.value}

    def _learn_failure(self, state, used_proc) -> dict[str, Any]:
        now = time.time()
        steps = state.plan.steps
        failed = next((s for s in reversed(steps) if s.status == StepStatus.FAILED), None)
        ftype = state.failure_classification or "unknown"
        attempted = [{"tool": s.tool} for s in steps if s.status != StepStatus.PENDING]
        pattern = tpl.task_pattern(attempted) if attempted else "none"
        last_obs = state.observations[-1] if state.observations else {}
        fexp = FailureExperience(
            task_pattern=pattern,
            failed_strategy=(state.strategy_type.value if state.strategy_type else "") +
                            (f":{used_proc.procedure_id}" if used_proc else ""),
            failure_type=ftype,
            reason=str((state.last_error or {}).get("message", ""))[:300],
            context={"goal": state.normalized_goal[:200], "failed_tool": failed.tool if failed else ""},
            observed_state={k: v for k, v in last_obs.items() if k in ("level", "active_window", "app", "current_url", "page_title")},
            better_strategy=LESSONS.get(ftype, "re-plan from the current observation instead of repeating the same steps"),
            procedure_id=used_proc.procedure_id if used_proc else "",
            template=tpl.normalize_request(state.raw_request).lower(),
            confidence=0.6,
        )
        if ftype in ("user_cancelled", "permission_denied"):
            fexp.confidence = 0.4   # policy outcomes, not evidence the strategy is wrong
        stored = self.store.record_failure(fexp)
        report = {"action": "failure", "failure_id": stored.failure_id, "failure_type": ftype}
        if used_proc is not None and ftype not in ("user_cancelled", "permission_denied"):
            used_proc.failure_count += 1
            used_proc.consecutive_failures += 1
            used_proc.usage_count += 1
            used_proc.last_used_at = now
            used_proc.known_failure_modes = (used_proc.known_failure_modes + [{"failure": ftype, "t": now}])[-5:]
            refresh(used_proc, now)
            self.store.upsert_procedure(used_proc, tpl.procedure_key(used_proc.steps))
            emit(state, "ExperienceUpdated", {"procedure_id": used_proc.procedure_id,
                                              "status": used_proc.status.value, "confidence": used_proc.confidence,
                                              "reason": "failure"})
            report.update(procedure_id=used_proc.procedure_id, status=used_proc.status.value)
        return report

    def _record_recovered_lessons(self, state: HarmaRunState, procedure_id: str, template: str) -> None:
        """A verified run that recovered from an error teaches a reusable lesson (spec §64)."""
        steps = state.plan.steps
        for i, s in enumerate(steps):
            if not s.error:   # in a verified run, every step carrying an error was recovered from
                continue
            err_type = (s.error or {}).get("type", "unknown")
            after = [toolmeta.humanize_step(x.tool, x.arguments) for x in steps[i + 1:i + 4]
                     if x.status == StepStatus.SUCCEEDED]
            better = (f"recovered by: {' → '.join(after)}" if after else LESSONS.get(err_type, ""))
            self.store.record_failure(FailureExperience(
                task_pattern=s.tool, failed_strategy=s.source, failure_type=err_type,
                reason=str((s.error or {}).get("message", ""))[:300],
                better_strategy=better, procedure_id=procedure_id, template=template, confidence=0.7,
            ))
            if procedure_id:
                proc = self.store.get_procedure(procedure_id)
                if proc is not None:
                    proc.known_failure_modes = (proc.known_failure_modes + [{
                        "failure": err_type, "step": s.tool, "lesson": better}])[-5:]
                    self.store.upsert_procedure(proc, tpl.procedure_key(proc.steps))

    def _record_facts(self, state: HarmaRunState, executed) -> None:
        for s in executed:
            if s.verification != VerificationState.VERIFIED:
                continue
            for k, v in s.arguments.items():
                if isinstance(v, str) and 1 < len(v) <= 60 and any(h in k.lower() for h in _APP_ARG_HINTS):
                    self.store.upsert_fact(SemanticFact(category="application", key=v, value=s.tool, confidence=0.7))

    # ── User feedback on the previous run ─────────────────────────────────────

    def apply_user_verdict(self, procedure_id: str, positive: bool) -> Optional[Procedure]:
        proc = self.store.get_procedure(procedure_id) if procedure_id else None
        if proc is None:
            return None
        if positive:
            proc.user_confirmations += 1
        else:
            proc.user_rejections += 1
            proc.consecutive_failures += 1
            if proc.status == ProcedureStatus.TRUSTED:
                proc.status = ProcedureStatus.CANDIDATE
        refresh(proc)
        self.store.upsert_procedure(proc, tpl.procedure_key(proc.steps))
        return proc
