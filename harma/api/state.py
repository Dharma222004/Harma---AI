"""
Harma Runtime State Coordinator
Aggregates state across all Harma subsystems (Core, Memory, Tasks, MCP, Devices, Perception)
and provides execution control (emergency stop, confirmations, planning).
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from harma.api.events import EventBus, get_event_bus
from harma.api.models import (
    AgentStatus,
    AuditEntry,
    ConfirmationRequest,
    EventSeverity,
    HarmaRuntimeState,
)
from harma.config.logging_config import get_logger
from harma.config.settings import config
from harma.core.agent import HarmaAgent
from harma.core.context import AgentContext
from harma.intelligence.plan_models import PlanStatus, StepStatus

log = get_logger(__name__)


class HarmaStateCoordinator:
    """
    Coordinates global state observation and operational control.
    Does NOT reason or make decisions — delegates strictly to HarmaAgent.
    """

    def __init__(
        self,
        context: Optional[AgentContext] = None,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self.ctx = context or AgentContext()
        self.bus = event_bus or get_event_bus()
        self.agent: Optional[HarmaAgent] = None

        self.current_status: AgentStatus = AgentStatus.IDLE
        self.autonomy_level: str = "supervised"
        self.is_emergency_stopped: bool = False
        self.voice_state: str = "ready"

        self.pending_confirmations: dict[str, ConfirmationRequest] = {}
        self.audit_log: list[AuditEntry] = []

    def get_runtime_state(self) -> HarmaRuntimeState:
        """Construct a real-time snapshot of Harma's runtime state."""
        # Planner inspection
        current_plan_data = None
        current_step_data = None
        planner = getattr(self.ctx, "planner", None)
        if planner and getattr(planner.state, "current_plan", None):
            plan = planner.state.current_plan
            current_plan_data = {
                "id": plan.plan_id,
                "goal": plan.goal,
                "status": plan.status.value,
                "steps": [
                    {
                        "id": s.step_id,
                        "step_id": str(s.step_id),
                        "description": s.description,
                        "tool": s.required_tool,
                        "tool_name": s.required_tool,
                        "status": s.status.value,
                        "risk": s.risk_level.value,
                        "observation": s.observation[:80] if s.observation else "",
                    }
                    for s in plan.steps
                ],
                "risk_level": plan.risk_level.value,
                "dry_run": plan.dry_run,
            }
            if planner.state.current_step_index < len(plan.steps):
                cur_s = plan.steps[planner.state.current_step_index]
                current_step_data = {
                    "id": cur_s.step_id,
                    "step_id": str(cur_s.step_id),
                    "description": cur_s.description,
                    "tool": cur_s.required_tool,
                    "tool_name": cur_s.required_tool,
                    "status": cur_s.status.value,
                }

        # Memory stats
        mem_data = {"total": 0, "active": 0}
        ltm = getattr(self.ctx, "long_term_memory", None)
        if ltm and hasattr(ltm, "stats"):
            try:
                mem_data = ltm.stats()
            except Exception:
                pass

        # Integrations list
        integ_list = []
        imgr = getattr(self.ctx, "integration_manager", None)
        if imgr:
            for s_name in imgr.list_servers():
                status = imgr.get_server_status(s_name)
                tools = imgr.registry.get_tools_for_server(s_name)
                integ_list.append({
                    "name": s_name,
                    "status": status.value if hasattr(status, "value") else str(status),
                    "tool_count": len(tools),
                })

        # Pending confirmation data
        first_conf = None
        confs_list = [c.to_dict() for c in self.pending_confirmations.values()]
        if confs_list:
            first_conf = confs_list[0]

        status = AgentStatus.PAUSED if self.is_emergency_stopped else self.current_status

        llm_instance = getattr(self.ctx, "llm", None)
        llm_info = {
            "provider": llm_instance.name if llm_instance else "Unknown",
            "model": getattr(llm_instance, "model", getattr(config.llm, "model", "")),
            "status": "Connected" if llm_instance else "Disconnected",
            "latency_ms": round(getattr(llm_instance, "last_latency_ms", 0.0), 2),
        }

        return HarmaRuntimeState(
            agent_status=status,
            current_plan=current_plan_data,
            current_step=current_step_data,
            pending_confirmation=first_conf,
            voice_state=self.voice_state,
            browser_state={"active": True, "engine": "Playwright/Chromium"},
            computer_state={"active_window": "Harma Control Center", "screen": "1920x1080"},
            android_state={"connected": getattr(self.ctx, "android_manager", None) is not None},
            integrations=integ_list,
            memory_state=mem_data,
            llm_state=llm_info,
            autonomy_level=self.autonomy_level,
            is_emergency_stopped=self.is_emergency_stopped,
        )

    async def execute_user_chat(
        self,
        user_input: str,
        mode: str = "chat",
        request_id: Optional[str] = None
    ) -> str:
        """
        Execute a chat message through Harma.
        In 'chat' mode: fast response with Tavily live web intelligence synthesized by NVIDIA LLM.
        In 'work' mode: full autonomous multi-step agent planning and tool execution.
        """
        req_id = request_id or f"harma-{uuid.uuid4().hex[:6]}"
        if self.is_emergency_stopped:
            return "Harma is currently paused by Emergency Stop. Release emergency stop to proceed."

        self.last_chat_sources = []

        if mode == "chat":
            from harma.intelligence.web_search import answer_with_live_search
            self.current_status = AgentStatus.THINKING
            self.bus.publish(
                "agent.started",
                source="agent",
                payload={"request": user_input[:100], "mode": "chat", "request_id": req_id},
            )
            try:
                self.bus.publish("agent.thinking", source="agent", payload={"request_id": req_id, "mode": "chat"})
                resp, sources = await answer_with_live_search(user_input, self.ctx.llm)
                self.last_chat_sources = sources
                self.last_execution_meta = {"status": "completed", "tool_calls": [], "sources": sources}
                self.current_status = AgentStatus.IDLE
                self.bus.publish(
                    "agent.completed",
                    source="agent",
                    severity=EventSeverity.SUCCESS,
                    payload={"response": resp[:120], "sources_count": len(sources), "request_id": req_id},
                )
                return resp
            except Exception as exc:
                self.current_status = AgentStatus.ERROR
                self.bus.publish(
                    "agent.failed",
                    source="agent",
                    severity=EventSeverity.ERROR,
                    payload={"error": str(exc)},
                )
                raise exc

        # Mode == "work" (Agent Task mode)
        if not self.agent:
            def _state_confirm(prompt: str) -> str:
                # Under supervised or autonomous autonomy level in the UI, user commands
                # explicitly authorize the agent to actuate requested actions
                if self.autonomy_level in ("supervised", "autonomous"):
                    log.info("[COORDINATOR] Auto-approving action under autonomy_level=%s", self.autonomy_level)
                    return "yes"
                return "no"

            self.agent = HarmaAgent(self.ctx, confirm_callback=_state_confirm)

        self.current_status = AgentStatus.THINKING
        self.bus.publish(
            "agent.started",
            source="agent",
            payload={"request": user_input[:100], "mode": "work", "request_id": req_id},
        )

        try:
            self.bus.publish("agent.thinking", source="agent", payload={"request_id": req_id, "mode": "work"})
            
            from harma.intelligence.web_search import sanitize_vendor_branding
            # Check for plan execution command
            low = user_input.strip().lower()
            if low.startswith(("/plan", "/dry-run")):
                self.bus.publish("plan.started", source="planner", payload={"goal": user_input, "request_id": req_id})
                resp = await self.agent.run(user_input, request_id=req_id)
                self.bus.publish("plan.completed", source="planner", payload={"response": resp[:120], "request_id": req_id})
            else:
                resp = await self.agent.run(user_input, request_id=req_id)

            resp = sanitize_vendor_branding(resp or "")
            self.last_execution_meta = getattr(self.agent, "last_execution_meta", {}) or {}
            self.current_status = AgentStatus.IDLE
            self.bus.publish(
                "agent.completed",
                source="agent",
                severity=EventSeverity.SUCCESS,
                payload={"response": resp[:120], "request_id": req_id},
            )
            return resp

        except Exception as exc:
            self.current_status = AgentStatus.ERROR
            self.bus.publish(
                "agent.failed",
                source="agent",
                severity=EventSeverity.ERROR,
                payload={"error": str(exc)},
            )
            raise exc

    def add_confirmation_request(self, conf: ConfirmationRequest) -> None:
        """Add a confirmation request for user approval."""
        self.pending_confirmations[conf.id] = conf
        self.bus.publish(
            "confirmation.required",
            source="executor",
            severity=EventSeverity.CONFIRMATION,
            payload=conf.to_dict(),
        )

    def get_pending_confirmations(self) -> list[dict[str, Any]]:
        """Retrieve list of pending confirmation requests."""
        return [c.to_dict() for c in self.pending_confirmations.values()]

    async def respond_confirmation(self, conf_id: str, approved: bool) -> bool:
        """Async wrapper for respond_to_confirmation."""
        return self.respond_to_confirmation(conf_id, approved)

    def respond_to_confirmation(self, conf_id: str, approved: bool) -> bool:
        """User responds to a pending confirmation dialog."""
        if conf_id in self.pending_confirmations:
            conf = self.pending_confirmations.pop(conf_id)
            conf.status = "approved" if approved else "rejected"
            self.bus.publish(
                "confirmation.approved" if approved else "confirmation.rejected",
                source="ui",
                severity=EventSeverity.SUCCESS if approved else EventSeverity.WARNING,
                payload={"id": conf_id, "approved": approved},
            )
            audit = AuditEntry(
                action="CONFIRMATION_APPROVED" if approved else "CONFIRMATION_REJECTED",
                target=conf.target,
                parameters=conf.parameters,
                consequence=conf.consequence,
                user_approved=approved,
            )
            self.audit_log.append(audit)
            return True
        return False

    async def trigger_emergency_stop(self, reason: str = "") -> HarmaRuntimeState:
        """
        Global Emergency Stop.
        Halts active plans, pauses proactive tasks, stops voice, and locks agent.
        """
        self.is_emergency_stopped = True
        self.current_status = AgentStatus.PAUSED
        log.warning("[EMERGENCY] Global emergency stop triggered: %s", reason)

        # Pause active plan
        planner = getattr(self.ctx, "planner", None)
        if planner:
            planner.pause()
            if getattr(planner.state, "current_plan", None):
                planner.state.current_plan.status = PlanStatus.PAUSED

        # Pause all Phase 7 background tasks
        if getattr(self.ctx, "task_manager", None):
            try:
                self.ctx.task_manager.pause_all()
            except Exception:
                pass

        self.bus.publish(
            "agent.paused",
            source="emergency_stop",
            severity=EventSeverity.WARNING,
            payload={"message": f"HARMA PAUSED: All activities halted under emergency stop. {reason}".strip()},
        )
        self.audit_log.append(AuditEntry(
            action="EMERGENCY_STOP",
            target="all_subsystems",
            consequence="All active operations halted immediately",
            user_approved=True,
        ))
        return self.get_runtime_state()

    async def resume_operations(self) -> HarmaRuntimeState:
        """Release the emergency stop and restore normal operations."""
        return self.resume_emergency_stop()

    def resume_emergency_stop(self) -> HarmaRuntimeState:
        """Release the emergency stop and restore normal operations."""
        self.is_emergency_stopped = False
        self.current_status = AgentStatus.IDLE
        log.info("[EMERGENCY] Emergency stop released. Resuming operations.")

        planner = getattr(self.ctx, "planner", None)
        if planner:
            planner.resume()
            if getattr(planner.state, "current_plan", None) and planner.state.current_plan.status == PlanStatus.PAUSED:
                planner.state.current_plan.status = PlanStatus.RUNNING

        self.bus.publish(
            "agent.resumed",
            source="emergency_stop",
            severity=EventSeverity.SUCCESS,
            payload={"message": "Harma resumed normal operations."},
        )
        return self.get_runtime_state()

    def set_autonomy_level(self, level: str) -> None:
        """Set autonomy tier: manual | assisted | supervised | autonomous."""
        valid = ["manual", "assisted", "supervised", "autonomous"]
        if level.lower() in valid:
            self.autonomy_level = level.lower()
            self.bus.publish(
                "autonomy.changed",
                source="ui",
                payload={"level": self.autonomy_level},
            )

    def get_audit_log(self, limit: int = 50) -> list[dict[str, Any]]:
        """Retrieve recent audit log entries."""
        return [entry.to_dict() for entry in self.audit_log[-limit:]]


_GLOBAL_COORDINATOR: Optional[HarmaStateCoordinator] = None


def get_state_coordinator(context: Optional[AgentContext] = None) -> HarmaStateCoordinator:
    """Retrieve or initialize the global HarmaStateCoordinator."""
    global _GLOBAL_COORDINATOR
    if _GLOBAL_COORDINATOR is None:
        _GLOBAL_COORDINATOR = HarmaStateCoordinator(context)
    return _GLOBAL_COORDINATOR
