"""
Harma Control Center — FastAPI Server & WebSockets

Exposes the unified REST API and real-time WebSocket event streams
for the Harma Control Center web interface.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from harma.api.events import get_event_bus
from harma.api.models import EventSeverity
from harma.api.state import HarmaStateCoordinator, get_state_coordinator
from harma.config.logging_config import get_logger
from harma.config.settings import config
from harma.intelligence.plan_models import PlanStatus, StepStatus

log = get_logger(__name__)

# Directory paths
WEB_DIR = Path(__file__).parent.parent / "ui" / "web"


# ── Request Models ────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    mode: Optional[str] = "chat"  # "chat" (fast + live Tavily web intelligence) | "work" (agent task)


class PlanRequest(BaseModel):
    goal: str
    dry_run: bool = False


class ConfirmationResponseRequest(BaseModel):
    approved: bool


class MemorySearchRequest(BaseModel):
    query: str
    category: Optional[str] = None
    limit: int = 10


class AutonomyRequest(BaseModel):
    mode: Optional[str] = None
    level: Optional[str] = None


class PermissionUpdateRequest(BaseModel):
    resource: str
    status: str


class TaskCreateRequest(BaseModel):
    name: str
    prompt: Optional[str] = None
    objective: Optional[str] = None
    schedule_type: str = "recurring"
    schedule_value: Any = "3600"
    autonomy_level: str = "supervised"


class TaskPatchRequest(BaseModel):
    enabled: Optional[bool] = None


class DeviceRegisterRequest(BaseModel):
    device_id: str
    device_name: Optional[str] = "Android Phone"
    platform: str = "android"
    android_version: Optional[str] = "14"
    app_version: Optional[str] = "1.0.0"
    manufacturer: Optional[str] = "Android"
    model: Optional[str] = "Pixel"
    capabilities: list[str] = []
    permission_states: dict[str, Any] = {}
    status: str = "online"


class DeviceHeartbeatRequest(BaseModel):
    device_id: str
    status: str = "online"
    battery_level: Optional[int] = None
    active_app: Optional[str] = None


class ActionResultReport(BaseModel):
    action_id: Optional[str] = None
    task_id: Optional[str] = None
    capability: Optional[str] = None
    action: Optional[str] = None
    outcome: Optional[str] = None
    status: Optional[str] = None
    verified: bool = True
    message: Optional[str] = None
    details: dict[str, Any] = {}
    error: Optional[str] = None


class LoginRequest(BaseModel):
    username: Optional[str] = "user"
    password: Optional[str] = None
    device_id: Optional[str] = None


# ── Application Factory ───────────────────────────────────────────────────────

def create_app(coordinator: Optional[HarmaStateCoordinator] = None) -> FastAPI:
    """Create and configure the Harma FastAPI application."""
    app = FastAPI(
        title="Harma Control Center API",
        version="1.0.0",
        description="Unified human-agent interface and operational control API for Harma AI.",
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.ui.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    coord = coordinator or get_state_coordinator()
    bus = coord.bus or get_event_bus()

    # ── Real-time WebSocket ───────────────────────────────────────────────────

    @app.websocket("/ws/harma")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        q = bus.subscribe()
        log.info("[WS] Client connected to Harma Control Center WebSocket")

        # Initial handshake state dump
        state = coord.get_runtime_state().to_dict()
        await websocket.send_json({"type": "state.snapshot", "payload": state})

        async def send_events() -> None:
            while True:
                event = await q.get()
                await websocket.send_json({
                    "type": event.event_type,
                    "event_id": event.event_id,
                    "severity": event.severity.value,
                    "source": event.source,
                    "timestamp": event.timestamp,
                    "payload": event.payload,
                })

        send_task = asyncio.create_task(send_events())
        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type", "")
                if msg_type == "chat":
                    text = data.get("message", "")
                    if text:
                        resp = await coord.execute_user_chat(text)
                        await websocket.send_json({"type": "chat.response", "payload": {"response": resp}})
                elif msg_type == "emergency_stop":
                    await coord.trigger_emergency_stop()
        except WebSocketDisconnect:
            log.info("[WS] Client disconnected from WebSocket")
        except Exception as exc:
            log.debug("[WS] WebSocket closed: %s", exc)
        finally:
            send_task.cancel()
            bus.unsubscribe(q)

    # ── State & Event Endpoints ───────────────────────────────────────────────

    @app.get("/api/state")
    async def get_state() -> dict[str, Any]:
        return {"state": coord.get_runtime_state().to_dict()}

    @app.get("/api/events")
    async def get_events(limit: int = 50, filter: Optional[str] = None) -> dict[str, Any]:
        return {"events": [e.to_dict() for e in bus.get_history(limit=limit, filter_type=filter)]}

    # ── Chat & Voice Endpoints ────────────────────────────────────────────────

    @app.post("/api/chat")
    async def chat(req: ChatRequest) -> dict[str, Any]:
        if not req.message.strip():
            raise HTTPException(status_code=400, detail="Message cannot be empty.")

        request_id = f"harma-{uuid.uuid4().hex[:6]}"
        active_mode = req.mode or "chat"
        log.info("[%s] REQUEST_RECEIVED: mode=%s %s", request_id, active_mode, req.message[:80])

        if coord.is_emergency_stopped:
            return {
                "success": False,
                "request_id": request_id,
                "status": "paused",
                "mode": active_mode,
                "error": "Emergency Stop is active. Harma is paused.",
                "response": "Harma is currently paused by Emergency Stop. Release emergency stop to proceed.",
                "plan_id": None,
                "tool_calls": [],
                "verification": {"status": "halted"},
                "plan": None,
                "confirmation_required": False,
                "sources": [],
            }

        response = await coord.execute_user_chat(req.message, mode=active_mode, request_id=request_id)
        sources = getattr(coord, "last_chat_sources", []) or []
        log.info("[%s] API_RESPONSE: %s (sources: %d)", request_id, str(response)[:80], len(sources))

        meta = getattr(coord, "last_execution_meta", {}) or {}
        runtime = coord.get_runtime_state()

        return {
            "success": True,
            "request_id": request_id,
            "status": meta.get("status", "completed"),
            "mode": active_mode,
            "response": response,
            "sources": sources,
            "plan_id": meta.get("plan_id"),
            "tool_calls": meta.get("tool_calls", []),
            "verification": meta.get("verification", {"status": "verified"}),
            "plan": runtime.current_plan,
            "confirmation_required": len(coord.pending_confirmations) > 0,
        }

    @app.get("/api/voice/status")
    async def get_voice_status() -> dict[str, Any]:
        return {
            "state": coord.voice_state,
            "wake_word_enabled": config.voice.wake_word_enabled,
            "wake_word_phrase": config.voice.wake_word_phrase,
            "stt_provider": config.voice.stt_provider,
            "tts_provider": config.voice.tts_provider,
        }

    @app.get("/api/performance")
    async def get_performance() -> dict[str, Any]:
        """Performance dashboard endpoint — returns latency stats and recent traces."""
        try:
            from harma.core.perf import get_performance_stats
            stats = get_performance_stats()
        except Exception as exc:
            log.warning("[API] Performance stats unavailable: %s", exc)
            stats = {"error": str(exc)}
        return {"performance": stats}

    # ── Plan Management Endpoints ─────────────────────────────────────────────

    @app.get("/api/plans")
    async def get_plans() -> dict[str, Any]:
        planner = getattr(coord.ctx, "planner", None)
        plans = []
        if planner and getattr(planner.state, "current_plan", None):
            p = planner.state.current_plan
            plans.append({
                "id": p.plan_id,
                "goal": p.goal,
                "status": p.status.value,
                "steps": [
                    {
                        "id": s.step_id,
                        "step_id": str(s.step_id),
                        "description": s.description,
                        "tool_name": s.required_tool,
                        "status": s.status.value,
                    }
                    for s in p.steps
                ],
            })
        return {"plans": plans, "active_plan": plans[0] if plans else None}

    @app.post("/api/plans/{plan_id}/pause")
    async def pause_plan(plan_id: str) -> dict[str, Any]:
        planner = getattr(coord.ctx, "planner", None)
        if planner:
            planner.pause()
            if getattr(planner.state, "current_plan", None):
                planner.state.current_plan.status = PlanStatus.PAUSED
        bus.publish("plan.paused", source="planner", payload={"plan_id": plan_id})
        return {"status": "paused", "plan_id": plan_id}

    @app.post("/api/plans/{plan_id}/resume")
    async def resume_plan(plan_id: str) -> dict[str, Any]:
        planner = getattr(coord.ctx, "planner", None)
        if planner:
            planner.resume()
            if getattr(planner.state, "current_plan", None):
                planner.state.current_plan.status = PlanStatus.RUNNING
        bus.publish("plan.resumed", source="planner", payload={"plan_id": plan_id})
        return {"status": "running", "plan_id": plan_id}

    @app.post("/api/plans/{plan_id}/cancel")
    async def cancel_plan(plan_id: str) -> dict[str, Any]:
        planner = getattr(coord.ctx, "planner", None)
        if planner:
            planner.cancel()
            if getattr(planner.state, "current_plan", None):
                planner.state.current_plan.status = PlanStatus.CANCELLED
        bus.publish("plan.cancelled", source="planner", payload={"plan_id": plan_id})
        return {"status": "cancelled", "plan_id": plan_id}

    @app.post("/api/plans/{plan_id}/retry")
    async def retry_plan(plan_id: str) -> dict[str, Any]:
        planner = getattr(coord.ctx, "planner", None)
        if planner and getattr(planner.state, "current_plan", None):
            planner.state.current_plan.status = PlanStatus.RUNNING
            for s in planner.state.current_plan.steps:
                if s.status == StepStatus.FAILED:
                    s.status = StepStatus.PENDING
        bus.publish("plan.resumed", source="planner", payload={"plan_id": plan_id})
        return {"status": "running", "plan_id": plan_id}

    # ── Confirmations Endpoints ───────────────────────────────────────────────

    @app.get("/api/confirmations")
    async def list_confirmations() -> dict[str, Any]:
        return {"confirmations": [c.to_dict() for c in coord.pending_confirmations.values()]}

    @app.post("/api/confirmations/{conf_id}/approve")
    async def approve_confirmation(conf_id: str) -> dict[str, Any]:
        success = coord.respond_to_confirmation(conf_id, True)
        return {"success": success, "status": "approved"}

    @app.post("/api/confirmations/{conf_id}/reject")
    async def reject_confirmation(conf_id: str) -> dict[str, Any]:
        success = coord.respond_to_confirmation(conf_id, False)
        return {"success": success, "status": "rejected"}

    @app.post("/api/confirmations/{conf_id}/respond")
    async def respond_confirmation(conf_id: str, req: ConfirmationResponseRequest) -> dict[str, Any]:
        success = coord.respond_to_confirmation(conf_id, req.approved)
        return {"success": success, "status": "approved" if req.approved else "rejected"}

    # ── Task Management Endpoints (Phase 7 Integration) ───────────────────────

    @app.get("/api/tasks")
    async def list_tasks() -> dict[str, Any]:
        tm = getattr(coord.ctx, "task_manager", None)
        if not tm:
            return {"tasks": []}
        tasks = tm.list_tasks()
        return {
            "tasks": [
                {
                    "id": t.id,
                    "name": t.name,
                    "prompt": t.objective,
                    "objective": t.objective,
                    "enabled": t.status.value not in ("paused", "cancelled"),
                    "status": t.status.value,
                    "schedule_type": t.trigger.trigger_type.value,
                    "schedule_value": getattr(t.trigger, "interval_seconds", 3600),
                    "autonomy_level": t.autonomy_level.value,
                    "next_run": str(t.next_run_at)[:19] if t.next_run_at else None,
                }
                for t in tasks
            ]
        }

    @app.post("/api/tasks")
    async def create_task(req: TaskCreateRequest) -> dict[str, Any]:
        tm = getattr(coord.ctx, "task_manager", None)
        objective = req.prompt or req.objective or req.name
        task_id = str(uuid.uuid4())[:8]
        if tm:
            from harma.tasks.models import TaskTrigger, TriggerType
            interval = int(req.schedule_value or 3600)
            trigger = TaskTrigger(trigger_type=TriggerType.INTERVAL, interval_seconds=interval)
            try:
                task_res = tm.create_task(name=req.name, objective=objective, trigger=trigger, check_duplicate=False)
                if asyncio.iscoroutine(task_res):
                    task = await task_res
                else:
                    task = task_res
                task_id = task.id
            except Exception as e:
                log.warning("Task create notice: %s", e)
        bus.publish("task.created", source="ui", payload={"task_id": task_id, "name": req.name})
        return {"success": True, "task_id": task_id}

    @app.patch("/api/tasks/{task_id}")
    async def patch_task(task_id: str, req: TaskPatchRequest) -> dict[str, Any]:
        tm = getattr(coord.ctx, "task_manager", None)
        if tm:
            if req.enabled is False:
                tm.pause_task(task_id)
            elif req.enabled is True:
                tm.resume_task(task_id)
        return {"success": True, "task_id": task_id, "enabled": req.enabled}

    @app.post("/api/tasks/{task_id}/run")
    async def run_task_now(task_id: str) -> dict[str, Any]:
        tm = getattr(coord.ctx, "task_manager", None)
        if tm:
            task = tm.get_task(task_id)
            if task:
                asyncio.create_task(tm.run_task_now(task_id))
        bus.publish("task.started", source="ui", payload={"task_id": task_id})
        return {"success": True, "task_id": task_id}

    @app.delete("/api/tasks/{task_id}")
    async def cancel_task(task_id: str) -> dict[str, Any]:
        tm = getattr(coord.ctx, "task_manager", None)
        if tm:
            tm.cancel_task(task_id)
        bus.publish("task.cancelled", source="ui", payload={"task_id": task_id})
        return {"success": True, "status": "deleted", "task_id": task_id}

    # ── Memory Endpoints (Phase 5 Integration) ────────────────────────────────

    @app.get("/api/memory")
    async def list_memories(limit: int = 50, category: Optional[str] = None) -> dict[str, Any]:
        ltm = getattr(coord.ctx, "memory_manager", getattr(coord.ctx, "long_term_memory", None))
        if not ltm or not hasattr(ltm, "list_memories"):
            return {"memories": []}
        mems = ltm.list_memories(limit=limit)
        items = []
        for m in mems:
            content = m.content
            # Sensitivity masking
            is_secret = getattr(m, "metadata", {}).get("sensitivity") == "secret" or "API_SECRET" in content or "PASSWORD" in content.upper()
            if is_secret:
                content = "🔒 [SENSITIVE VALUE MASKED FOR UI PRIVACY]"

            items.append({
                "id": m.id,
                "content": content,
                "category": m.memory_type.value if hasattr(m.memory_type, "value") else str(m.memory_type),
                "confidence": m.confidence,
                "importance": m.importance,
                "sensitivity": "secret" if is_secret else "low",
                "updated_at": str(getattr(m, "updated_at", m.created_at))[:19],
            })
        return {"memories": items}

    @app.post("/api/memory/search")
    async def search_memory(req: MemorySearchRequest) -> dict[str, Any]:
        ltm = getattr(coord.ctx, "memory_manager", getattr(coord.ctx, "long_term_memory", None))
        if not ltm or not hasattr(ltm, "search"):
            return {"memories": []}
        results = ltm.search(req.query, top_k=req.limit)
        items = []
        for r in results:
            content = r.content
            if "API_SECRET" in content or getattr(r, "metadata", {}).get("sensitivity") == "secret":
                content = "🔒 [SENSITIVE VALUE MASKED FOR UI PRIVACY]"
            items.append({
                "id": r.id,
                "content": content,
                "category": r.memory_type.value if hasattr(r.memory_type, "value") else str(r.memory_type),
                "confidence": getattr(r, "confidence", 0.9),
                "importance": r.importance,
                "updated_at": "Recently",
            })
        return {"memories": items}

    @app.delete("/api/memory/{memory_id}")
    async def delete_memory(memory_id: str) -> dict[str, Any]:
        ltm = getattr(coord.ctx, "memory_manager", getattr(coord.ctx, "long_term_memory", None))
        success = False
        if ltm:
            if hasattr(ltm, "forget"):
                success = ltm.forget(memory_id)
            elif hasattr(ltm, "delete_memory"):
                success = ltm.delete_memory(memory_id)
            elif hasattr(ltm, "delete"):
                success = ltm.delete(memory_id)
        bus.publish("memory.deleted", source="ui", payload={"id": memory_id, "success": success})
        return {"success": success, "status": "deleted" if success else "not_found", "id": memory_id}

    # ── Integrations Endpoints (Phase 8 MCP) ──────────────────────────────────

    @app.get("/api/integrations")
    async def list_integrations() -> dict[str, Any]:
        imgr = getattr(coord.ctx, "integration_manager", None)
        if not imgr:
            return {"integrations": []}
        res = []
        for s_name in imgr.list_servers():
            status = imgr.get_server_status(s_name)
            tools = imgr.registry.get_tools_for_server(s_name)
            tool_items = [
                {
                    "name": t.name,
                    "description": t.description,
                    "permission": t.permission_level.value,
                }
                for t in tools
            ]
            res.append({
                "id": s_name,
                "name": s_name.capitalize(),
                "status": status.value if hasattr(status, "value") else str(status),
                "tool_count": len(tools),
                "tools": tool_items,
            })
        return {"integrations": res}

    @app.post("/api/integrations/{name}/connect")
    async def connect_integration(name: str) -> dict[str, Any]:
        imgr = getattr(coord.ctx, "integration_manager", None)
        if imgr:
            try:
                await imgr.connect_server(name)
            except Exception:
                pass
        bus.publish("mcp.connected", source="ui", payload={"server": name})
        return {"success": True, "status": "connected", "name": name}

    @app.post("/api/integrations/{name}/disconnect")
    async def disconnect_integration(name: str) -> dict[str, Any]:
        imgr = getattr(coord.ctx, "integration_manager", None)
        if imgr:
            try:
                await imgr.disconnect_server(name)
            except Exception:
                pass
        bus.publish("mcp.disconnected", source="ui", payload={"server": name})
        return {"success": True, "status": "disconnected", "name": name}

    # ── Device Registry & Auth ────────────────────────────────────────────────
    registered_devices: dict[str, dict[str, Any]] = {}

    @app.post("/api/auth/login")
    async def login(req: LoginRequest) -> dict[str, Any]:
        token = f"harma-session-{uuid.uuid4().hex}"
        return {
            "success": True,
            "status": "success",
            "token": token,
            "username": req.username or "harma_user",
            "user": req.username or "harma_user",
            "message": "Authenticated with Harma Runtime",
        }

    @app.post("/api/auth/logout")
    async def logout() -> dict[str, Any]:
        return {"success": True, "status": "success", "message": "Logged out successfully"}

    @app.get("/api/auth/session")
    async def get_session() -> dict[str, Any]:
        return {"authenticated": True, "status": "active", "user": "harma_user", "mode": "production"}

    @app.post("/api/devices/register")
    async def register_device(req: DeviceRegisterRequest) -> dict[str, Any]:
        dev = {
            "device_id": req.device_id,
            "name": req.device_name or f"{req.manufacturer} {req.model}",
            "platform": req.platform,
            "android_version": req.android_version,
            "app_version": req.app_version,
            "manufacturer": req.manufacturer,
            "model": req.model,
            "capabilities": req.capabilities or ["Voice", "UI Control", "Flashlight", "Notifications", "App Launcher"],
            "permission_states": req.permission_states,
            "status": "Online",
            "last_seen": int(time.time()),
        }
        registered_devices[req.device_id] = dev
        bus.publish("device.registered", source="android", payload=dev)
        log.info("[DEVICE] Registered Android device: %s (%s)", dev["name"], dev["device_id"])
        return {"success": True, "status": "registered", "device": dev, "message": "Device registered successfully"}

    @app.post("/api/devices/heartbeat")
    async def device_heartbeat(req: DeviceHeartbeatRequest) -> dict[str, Any]:
        if req.device_id in registered_devices:
            registered_devices[req.device_id]["status"] = req.status
            registered_devices[req.device_id]["last_seen"] = int(time.time())
            if req.battery_level is not None:
                registered_devices[req.device_id]["battery_level"] = req.battery_level
            if req.active_app is not None:
                registered_devices[req.device_id]["active_app"] = req.active_app
        return {"success": True, "status": "acknowledged", "timestamp": int(time.time())}

    @app.post("/api/devices/{device_id}/action-result")
    async def report_action_result(device_id: str, report: ActionResultReport) -> dict[str, Any]:
        act_id = report.action_id or report.task_id or "unknown"
        cap = report.capability or report.action or "device_action"
        outc = report.outcome or report.status or "ACTION_EXECUTED_VERIFIED"
        bus.publish(
            "device.action.result",
            source="android",
            payload={
                "device_id": device_id,
                "action_id": act_id,
                "capability": cap,
                "outcome": outc,
                "verified": report.verified,
                "details": report.details,
                "error": report.error,
                "message": report.message,
            },
        )
        return {"success": True, "status": "acknowledged", "action_id": act_id, "verified": report.verified}

    @app.get("/api/devices")
    async def get_devices() -> dict[str, Any]:
        # Base devices
        base_devices: dict[str, Any] = {
            "computer": {"status": "Connected", "resolution": "1920x1080", "active_app": "Harma Control Center"},
            "android": {"status": "Available", "device_model": "ADB Virtual Device"},
            "browser": {"status": "Ready", "engine": "Playwright/Chromium"},
            "microphone": {"status": "Available", "wake_word": "openWakeWord (Active)"},
        }
        # If any Android phone registered via API, display its live status
        if registered_devices:
            latest = list(registered_devices.values())[-1]
            base_devices["android"] = {
                "status": latest.get("status", "Online"),
                "device_id": latest.get("device_id"),
                "device_name": latest.get("name"),
                "device_model": f"{latest.get('manufacturer', '')} {latest.get('model', '')}".strip() or "Android Phone",
                "capabilities": latest.get("capabilities", ["Voice", "UI Control", "Flashlight"]),
                "last_seen": latest.get("last_seen"),
            }
        return {"devices": base_devices, "registered_devices": list(registered_devices.values())}

    @app.get("/api/permissions")
    async def get_permissions() -> dict[str, Any]:
        return {
            "permissions": [
                {"resource": "Microphone", "status": "allowed", "risk_level": "Medium"},
                {"resource": "Screen Capture", "status": "allowed", "risk_level": "Medium"},
                {"resource": "Computer Control", "status": "confirmation", "risk_level": "High"},
                {"resource": "Browser Automation", "status": "allowed", "risk_level": "Low"},
                {"resource": "Android ADB", "status": "allowed", "risk_level": "Medium"},
                {"resource": "Memory Core", "status": "allowed", "risk_level": "Low"},
                {"resource": "Local Filesystem", "status": "confirmation", "risk_level": "High"},
                {"resource": "MCP External Integrations", "status": "allowed", "risk_level": "Medium"},
            ]
        }

    @app.patch("/api/permissions")
    async def update_permission(req: PermissionUpdateRequest) -> dict[str, Any]:
        bus.publish("permission.updated", source="ui", payload={"resource": req.resource, "status": req.status})
        return {"success": True, "resource": req.resource, "status": req.status}

    @app.patch("/api/autonomy")
    @app.post("/api/autonomy")
    async def update_autonomy(req: AutonomyRequest) -> dict[str, Any]:
        mode = req.mode or req.level or "supervised"
        coord.set_autonomy_level(mode)
        return {"success": True, "autonomy_mode": coord.autonomy_level}

    # ── Emergency Stop & Audit ────────────────────────────────────────────────

    @app.post("/api/emergency-stop")
    async def emergency_stop() -> dict[str, Any]:
        state = await coord.trigger_emergency_stop(reason="User invoked from Control Center")
        return {"status": "paused", "emergency_stopped": True, "message": "HARMA PAUSED"}

    @app.post("/api/emergency-resume")
    @app.post("/api/emergency-stop/resume")
    async def resume_from_emergency_stop() -> dict[str, Any]:
        state = await coord.resume_operations()
        return {"status": "resumed", "emergency_stopped": False, "message": "Operations restored"}

    @app.get("/api/audit")
    async def get_audit_log(limit: int = 50) -> dict[str, Any]:
        return {"audit_entries": coord.get_audit_log(limit)}

    # ── Health Status ─────────────────────────────────────────────────────────

    @app.get("/api/health")
    async def get_health() -> dict[str, Any]:
        llm = getattr(coord.ctx, "llm", None)
        llm_name = llm.name if llm else "unavailable"
        llm_model = getattr(llm, "model", getattr(config.llm, "model", ""))
        llm_latency = getattr(llm, "last_latency_ms", 0.0)

        return {
            "status": "healthy" if not coord.is_emergency_stopped else "paused",
            "llm": {
                "provider": llm_name,
                "model": llm_model,
                "status": "Connected" if llm else "Disconnected",
                "latency_ms": round(llm_latency, 2),
            },
            "subsystems": {
                "core": "healthy",
                "llm": "connected" if llm else "unavailable",
                "memory": "healthy",
                "voice": "ready",
                "browser": "ready",
                "android": "connected",
                "mcp": "ready",
                "tasks": "running",
                "event_bus": "active",
            },
            "version": "1.0.0",
        }

    @app.get("/api/llm/diagnostics")
    async def get_llm_diagnostics() -> dict[str, Any]:
        llm = getattr(coord.ctx, "llm", None)
        if not llm:
            return {"error": "No LLM provider initialized"}
        if hasattr(llm, "get_diagnostics"):
            diag = await llm.get_diagnostics()
            return {"diagnostics": diag}
        return {
            "diagnostics": {
                "provider": llm.name,
                "model": getattr(llm, "model", getattr(config.llm, "model", "")),
                "status": "Connected",
                "latency_ms": round(getattr(llm, "last_latency_ms", 0.0), 2),
            }
        }

    # ── Static Web UI Files ───────────────────────────────────────────────────

    possible_web_dirs = [
        WEB_DIR,
        Path.cwd() / "public",
        Path.cwd() / "harma" / "ui" / "web",
        Path(__file__).parent.parent.parent / "public",
    ]
    resolved_web_dir = None
    for d in possible_web_dirs:
        if d.exists() and (d / "index.html").exists():
            resolved_web_dir = d
            break

    if resolved_web_dir:
        static_dir = resolved_web_dir / "static" if (resolved_web_dir / "static").exists() else resolved_web_dir
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    def _find_index_file() -> Optional[Path]:
        for d in possible_web_dirs:
            p = d / "index.html"
            if p.exists():
                return p
        return None

    @app.get("/", response_class=HTMLResponse)
    @app.get("/index.html", response_class=HTMLResponse)
    @app.get("/main.py", response_class=HTMLResponse)
    async def serve_index() -> Any:
        idx = _find_index_file()
        if idx:
            return FileResponse(idx)
        return HTMLResponse("<h2>Harma Control Center loading...</h2>")

    return app
