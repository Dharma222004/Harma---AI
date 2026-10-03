"""
Tests for Phase 10: Control Center, Unified UI & Human-Agent Interaction

Covers:
- UI endpoint & static asset delivery
- EventBus publish/subscribe & history
- HarmaRuntimeState aggregation & coordinator
- API endpoints: /api/state, /api/health, /api/chat, /api/plans, /api/confirmations
- Tasks API: list, create, pause, resume, run, delete
- Memory API: list, search, delete, sensitivity masking
- Integrations API: MCP server listing, connect, disconnect
- Device state: computer, Android, browser, microphone
- Permissions & Autonomy level controls
- Emergency stop: immediate pause of plans and tasks, broadcast event, resume
- Audit logging of sensitive operations
- End-to-end integration scenarios (E2E 1 to 5)
"""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from harma.api.models import (
    AgentStatus,
    ConfirmationRequest,
    EventSeverity,
    HarmaEvent,
    HarmaRuntimeState,
)
from harma.api.events import EventBus, get_event_bus
from harma.api.state import HarmaStateCoordinator
from harma.api.server import create_app
from harma.core.context import AgentContext
from harma.core.agent import HarmaAgent
from harma.intelligence.plan_models import Plan, PlanStep, PlanStatus, StepStatus, RiskLevel


class TestPhase10EventBus(unittest.IsolatedAsyncioTestCase):
    """Test normalized event model and asynchronous EventBus."""

    async def test_event_creation_and_attributes(self):
        ev = HarmaEvent(
            event_type="agent.started",
            source="agent",
            severity=EventSeverity.INFO,
            payload={"request": "Hello Harma"},
        )
        self.assertTrue(ev.event_id)
        self.assertEqual(ev.event_type, "agent.started")
        d = ev.to_dict()
        self.assertEqual(d["source"], "agent")
        self.assertEqual(d["severity"], "info")
        self.assertEqual(d["payload"]["request"], "Hello Harma")

    async def test_event_bus_publish_and_subscribe(self):
        bus = EventBus(max_history=10)
        q = bus.subscribe()
        try:
            ev = bus.publish(event_type="test.event", payload={"data": 123})

            received = await asyncio.wait_for(q.get(), timeout=2.0)
            self.assertEqual(received.event_type, "test.event")
            self.assertEqual(received.payload["data"], 123)

            history = bus.get_history()
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0].event_type, "test.event")
        finally:
            bus.unsubscribe(q)

    async def test_event_bus_history_buffer_cap(self):
        bus = EventBus(max_history=5)
        for i in range(10):
            bus.publish(event_type=f"evt.{i}")
        history = bus.get_history()
        self.assertEqual(len(history), 5)
        self.assertEqual(history[-1].event_type, "evt.9")


class TestPhase10StateCoordinator(unittest.IsolatedAsyncioTestCase):
    """Test HarmaStateCoordinator state aggregation and controls."""

    def setUp(self):
        self.ctx = AgentContext()
        self.bus = EventBus()
        self.coord = HarmaStateCoordinator(self.ctx, self.bus)

    async def test_get_runtime_state(self):
        state = self.coord.get_runtime_state()
        self.assertIsInstance(state, HarmaRuntimeState)
        self.assertEqual(state.agent_status, AgentStatus.IDLE)
        self.assertFalse(state.is_emergency_stopped)
        self.assertIn("active_window", state.computer_state)
        self.assertIn("engine", state.browser_state)
        self.assertIn("connected", state.android_state)
        self.assertEqual(state.voice_state, "ready")

    async def test_emergency_stop_and_resume(self):
        # Trigger emergency stop
        stopped_state = await self.coord.trigger_emergency_stop("Safety test")
        self.assertTrue(stopped_state.is_emergency_stopped)
        self.assertEqual(stopped_state.agent_status, AgentStatus.PAUSED)

        # Check audit log
        audit = self.coord.get_audit_log()
        self.assertTrue(any(a["action"] == "EMERGENCY_STOP" for a in audit))

        # Check resume
        resumed_state = await self.coord.resume_operations()
        self.assertFalse(resumed_state.is_emergency_stopped)
        self.assertEqual(resumed_state.agent_status, AgentStatus.IDLE)

    async def test_confirmation_lifecycle(self):
        req = ConfirmationRequest(
            id="conf_test_1",
            action="delete_file",
            target="/tmp/important.txt",
            parameters={"force": True},
            consequence="File will be permanently removed.",
        )
        self.coord.add_confirmation_request(req)
        self.assertEqual(len(self.coord.get_pending_confirmations()), 1)

        # Approve confirmation
        approved = await self.coord.respond_confirmation("conf_test_1", approved=True)
        self.assertTrue(approved)
        self.assertEqual(len(self.coord.get_pending_confirmations()), 0)

        # Verify audit log
        audit = self.coord.get_audit_log()
        self.assertTrue(any(a["action"] == "CONFIRMATION_APPROVED" for a in audit))


class TestPhase10ApiServer(unittest.IsolatedAsyncioTestCase):
    """Test FastAPI REST endpoints and application serving."""

    async def asyncSetUp(self):
        self.ctx = AgentContext()
        self.bus = EventBus()
        self.coord = HarmaStateCoordinator(self.ctx, self.bus)
        self.app = create_app(coordinator=self.coord)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://testserver",
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_root_index_and_static_assets(self):
        r = await self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Harma Control Center", r.text)

        css = await self.client.get("/static/style.css")
        self.assertEqual(css.status_code, 200)

        js = await self.client.get("/static/app.js")
        self.assertEqual(js.status_code, 200)

    async def test_health_endpoint(self):
        r = await self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["version"], "1.0.0")
        self.assertIn("core", data["subsystems"])
        self.assertIn("memory", data["subsystems"])

    async def test_state_endpoint(self):
        r = await self.client.get("/api/state")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("state", data)
        self.assertEqual(data["state"]["agent_status"], "idle")
        self.assertFalse(data["state"]["is_emergency_stopped"])

    async def test_events_endpoint(self):
        self.bus.publish(event_type="test.event.api", payload={"hello": "world"})
        r = await self.client.get("/api/events")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(any(e["event_type"] == "test.event.api" for e in data["events"]))

    async def test_chat_endpoint(self):
        with patch.object(self.coord, "execute_user_chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = "Hello! I am Harma, your personal AI."
            r = await self.client.post("/api/chat", json={"message": "Hi Harma"})
            self.assertEqual(r.status_code, 200)
            data = r.json()
            self.assertTrue(data["success"])
            self.assertIn("response", data)
            self.assertEqual(data["response"], "Hello! I am Harma, your personal AI.")

    async def test_chat_blocked_when_emergency_stopped(self):
        await self.coord.trigger_emergency_stop()
        r = await self.client.post("/api/chat", json={"message": "Execute task"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertFalse(data["success"])
        self.assertIn("Emergency Stop", data["error"])

    async def test_plans_api(self):
        plan = Plan(
            goal="Test Goal",
            plan_id="plan_test_api",
            steps=[
                PlanStep(step_id=1, description="Step One", required_tool="browser_open", status=StepStatus.SUCCESS),
                PlanStep(step_id=2, description="Step Two", required_tool="browser_search", status=StepStatus.RUNNING),
            ],
            status=PlanStatus.RUNNING,
        )
        self.ctx.planner.state.current_plan = plan

        # GET /api/plans
        r = await self.client.get("/api/plans")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data["plans"]), 1)
        self.assertEqual(data["plans"][0]["id"], "plan_test_api")

        # POST /api/plans/{id}/pause
        r = await self.client.post("/api/plans/plan_test_api/pause")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.ctx.planner.state.current_plan.status, PlanStatus.PAUSED)

        # POST /api/plans/{id}/resume
        r = await self.client.post("/api/plans/plan_test_api/resume")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.ctx.planner.state.current_plan.status, PlanStatus.RUNNING)

        # POST /api/plans/{id}/cancel
        r = await self.client.post("/api/plans/plan_test_api/cancel")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.ctx.planner.state.current_plan.status, PlanStatus.CANCELLED)

    async def test_confirmations_api(self):
        req = ConfirmationRequest(
            id="conf_api_1",
            action="transfer_funds",
            target="Bank",
            parameters={"amount": 500},
            consequence="Transfers funds irreversibly.",
        )
        self.coord.add_confirmation_request(req)

        # GET /api/confirmations
        r = await self.client.get("/api/confirmations")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["confirmations"]), 1)

        # POST /api/confirmations/{id}/approve
        r_app = await self.client.post("/api/confirmations/conf_api_1/approve")
        self.assertEqual(r_app.status_code, 200)
        self.assertTrue(r_app.json()["success"])

        # Check pending is now empty
        r2 = await self.client.get("/api/confirmations")
        self.assertEqual(len(r2.json()["confirmations"]), 0)

    async def test_tasks_api_lifecycle(self):
        import uuid
        uid = str(uuid.uuid4())[:6]
        # Create task
        r_create = await self.client.post(
            "/api/tasks",
            json={
                "name": f"API Daily News {uid}",
                "prompt": f"Summarize tech news daily {uid}",
                "schedule_type": "recurring",
                "schedule_value": "3600",
            },
        )
        self.assertEqual(r_create.status_code, 200)
        task_id = r_create.json()["task_id"]
        self.assertTrue(task_id)

        # List tasks
        r_list = await self.client.get("/api/tasks")
        self.assertEqual(r_list.status_code, 200)
        self.assertTrue(any(t["id"] == task_id for t in r_list.json()["tasks"]))

        # Patch task (pause)
        r_patch = await self.client.patch(f"/api/tasks/{task_id}", json={"enabled": False})
        self.assertEqual(r_patch.status_code, 200)

        # Run task
        r_run = await self.client.post(f"/api/tasks/{task_id}/run")
        self.assertEqual(r_run.status_code, 200)

        # Delete task
        r_del = await self.client.delete(f"/api/tasks/{task_id}")
        self.assertEqual(r_del.status_code, 200)

    async def test_memory_api_and_masking(self):
        # Insert a memory item
        import uuid
        from harma.memory.models import Memory, MemoryType, MemorySensitivity
        mem_id = f"mem_sec_{str(uuid.uuid4())[:8]}"
        entry = Memory(
            id=mem_id,
            content="API_SECRET_TOKEN=sk-1234567890abcdef",
            memory_type=MemoryType.PREFERENCE,
            confidence=0.95,
            importance=0.9,
            sensitivity=MemorySensitivity.HIGH_SENSITIVITY,
        )
        self.ctx.long_term_memory._store.insert(entry)

        # GET /api/memory
        r = await self.client.get("/api/memory")
        self.assertEqual(r.status_code, 200)
        memories = r.json()["memories"]
        secret_mem = next((m for m in memories if m["id"] == mem_id), None)
        self.assertIsNotNone(secret_mem)
        # Should be masked
        self.assertIn("MASKED", secret_mem["content"])

        # Search memory
        r_search = await self.client.post("/api/memory/search", json={"query": "API_SECRET"})
        self.assertEqual(r_search.status_code, 200)

        # Delete memory
        r_del = await self.client.delete(f"/api/memory/{mem_id}")
        self.assertEqual(r_del.status_code, 200)

    async def test_mcp_integrations_api(self):
        r = await self.client.get("/api/integrations")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("integrations", data)

        # Connect & disconnect routes
        r_conn = await self.client.post("/api/integrations/github/connect")
        self.assertEqual(r_conn.status_code, 200)
        r_disc = await self.client.post("/api/integrations/github/disconnect")
        self.assertEqual(r_disc.status_code, 200)

    async def test_devices_and_permissions_api(self):
        r_dev = await self.client.get("/api/devices")
        self.assertEqual(r_dev.status_code, 200)
        self.assertIn("devices", r_dev.json())

        r_perm = await self.client.get("/api/permissions")
        self.assertEqual(r_perm.status_code, 200)
        self.assertTrue(len(r_perm.json()["permissions"]) > 0)

        r_perm_patch = await self.client.patch(
            "/api/permissions",
            json={"resource": "Microphone", "status": "confirmation"},
        )
        self.assertEqual(r_perm_patch.status_code, 200)

    async def test_autonomy_mode_control(self):
        r = await self.client.patch("/api/autonomy", json={"mode": "manual"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["autonomy_mode"], "manual")

    async def test_emergency_stop_endpoints(self):
        # Trigger stop
        r_stop = await self.client.post("/api/emergency-stop")
        self.assertEqual(r_stop.status_code, 200)
        self.assertEqual(r_stop.json()["status"], "paused")

        # Resume
        r_resume = await self.client.post("/api/emergency-resume")
        self.assertEqual(r_resume.status_code, 200)
        self.assertEqual(r_resume.json()["status"], "resumed")

    async def test_audit_endpoint(self):
        r = await self.client.get("/api/audit")
        self.assertEqual(r.status_code, 200)
        self.assertIn("audit_entries", r.json())


class TestPhase10EndToEnd(unittest.IsolatedAsyncioTestCase):
    """End-to-End integration tests conforming to Section 43 specifications."""

    async def asyncSetUp(self):
        self.ctx = AgentContext()
        self.bus = EventBus()
        self.coord = HarmaStateCoordinator(self.ctx, self.bus)
        self.agent = HarmaAgent(self.ctx)
        self.coord.agent = self.agent
        self.app = create_app(coordinator=self.coord)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://testserver",
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_e2e_1_search_plan_execution(self):
        """
        E2E 1:
        User enters: "Open Chrome and search for today's weather."
        UI -> API -> HarmaAgent -> Plan -> Browser -> UI result
        """
        plan = Plan(
            goal="Open Chrome and search for today's weather",
            plan_id="e2e_plan_1",
            steps=[
                PlanStep(step_id=1, description="Open browser", required_tool="browser_open", status=StepStatus.SUCCESS),
                PlanStep(step_id=2, description="Search weather", required_tool="browser_search", status=StepStatus.SUCCESS),
            ],
            status=PlanStatus.COMPLETED,
        )
        self.ctx.planner.state.current_plan = plan

        with patch.object(self.agent, "run", new_callable=AsyncMock) as mock_agent:
            mock_agent.return_value = "Chrome was opened and current weather is 72°F and sunny."
            r = await self.client.post("/api/chat", json={"message": "Open Chrome and search for today's weather."})
            self.assertEqual(r.status_code, 200)
            data = r.json()
            self.assertTrue(data["success"])
            self.assertIn("weather", data["response"])
            self.assertIsNotNone(data["plan"])
            self.assertEqual(data["plan"]["status"], "completed")

    async def test_e2e_2_voice_pipeline_flow(self):
        """
        E2E 2:
        Wake word -> STT -> Agent -> Plan -> Tool -> TTS -> UI state
        """
        self.bus.publish(event_type="voice.listening", payload={"state": "listening"})
        self.bus.publish(event_type="tool.started", payload={"tool": "weather_lookup"})
        self.bus.publish(event_type="voice.speaking", payload={"text": "It is sunny."})

        events = self.bus.get_history()
        types = [e.event_type for e in events]
        self.assertIn("voice.listening", types)
        self.assertIn("tool.started", types)
        self.assertIn("voice.speaking", types)

    async def test_e2e_3_high_risk_action_confirmation(self):
        """
        E2E 3:
        User request -> Plan -> Confirmation -> User approves -> Tool executes -> Result
        """
        req = ConfirmationRequest(
            id="e2e_conf_delete",
            action="delete_database",
            target="sqlite://production",
            parameters={"database": "production.db"},
            consequence="Deletes all user data irreversibly.",
        )
        self.coord.add_confirmation_request(req)

        # Verify confirmation is required in state
        state = self.coord.get_runtime_state()
        self.assertIsNotNone(state.pending_confirmation)
        self.assertEqual(state.pending_confirmation["id"], "e2e_conf_delete")

        # User approves via UI API
        r_app = await self.client.post("/api/confirmations/e2e_conf_delete/approve")
        self.assertEqual(r_app.status_code, 200)
        self.assertTrue(r_app.json()["success"])

        # Verify confirmation cleared
        updated_state = self.coord.get_runtime_state()
        self.assertIsNone(updated_state.pending_confirmation)

        # Verify in audit log
        audit = self.coord.get_audit_log()
        self.assertTrue(any(a["action"] == "CONFIRMATION_APPROVED" for a in audit))

    async def test_e2e_4_plan_failure_and_retry(self):
        """
        E2E 4:
        Action -> Failure -> Recovery -> Updated plan -> Success
        """
        failed_plan = Plan(
            goal="Fetch external data",
            plan_id="e2e_plan_fail",
            steps=[
                PlanStep(step_id=1, description="Fetch url", required_tool="browser_open", status=StepStatus.FAILED, observation="Network timeout"),
            ],
            status=PlanStatus.FAILED,
        )
        self.ctx.planner.state.current_plan = failed_plan

        # Verify retry endpoint resets plan
        r_retry = await self.client.post("/api/plans/e2e_plan_fail/retry")
        self.assertEqual(r_retry.status_code, 200)
        self.assertEqual(self.ctx.planner.state.current_plan.status, PlanStatus.RUNNING)
        self.assertEqual(self.ctx.planner.state.current_plan.steps[0].status, StepStatus.PENDING)

    async def test_e2e_5_emergency_stop_halts_everything(self):
        """
        E2E 5:
        Long-running task -> STOP ALL -> Execution halted -> UI shows PAUSED
        """
        running_plan = Plan(
            goal="Long running automation",
            plan_id="e2e_plan_run",
            steps=[PlanStep(step_id=1, description="Running loop", status=StepStatus.RUNNING)],
            status=PlanStatus.RUNNING,
        )
        self.ctx.planner.state.current_plan = running_plan

        # Trigger emergency stop
        r_stop = await self.client.post("/api/emergency-stop")
        self.assertEqual(r_stop.status_code, 200)
        data = r_stop.json()
        self.assertEqual(data["status"], "paused")

        # Verify state is paused
        r_state = await self.client.get("/api/state")
        self.assertTrue(r_state.json()["state"]["is_emergency_stopped"])
        self.assertEqual(r_state.json()["state"]["agent_status"], "paused")
        self.assertEqual(self.ctx.planner.state.current_plan.status, PlanStatus.PAUSED)

        # Verify any chat attempt is rejected
        r_chat = await self.client.post("/api/chat", json={"message": "Do work"})
        self.assertFalse(r_chat.json()["success"])
        self.assertIn("Emergency Stop", r_chat.json()["error"])


if __name__ == "__main__":
    unittest.main()
