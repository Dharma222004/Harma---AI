"""
Harma Phase 7 Test Suite — Proactive Agent, Background Tasks & Autonomous Execution

Comprehensive tests covering:
  1. Task Data Models, Triggers & Serialization (Sec 3, 4)
  2. Timezone-Aware Scheduler & Controllable Clock (Sec 5, 6, 48)
  3. Persistence & Restart Recovery (Sec 7, 8)
  4. Task Executor, Agent Core Integration & Limits (Sec 13, 16, 21, 22, 23, 43)
  5. Error Classification & Bounded Retries (Sec 19, 20)
  6. Autonomy Levels & Tool Allowlists (Sec 12, 14, 15, 38, 40)
  7. Concurrency & Per-Task Locking (Sec 35, 37)
  8. Conditional Tasks & Polling Limits (Sec 28, 29)
  9. Notifications & Quiet Hours (Sec 25, 26, 27)
 10. Security, Prompt-Injection & Scope Integrity (Sec 38, 39, 40)
 11. Section 49 Real-World Integration Scenarios (Tests 1–6)
 12. Task Management Tools, CLI & Emergency Stop (Sec 10, 32, 33, 41, 45)
"""

from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from harma.core.agent import HarmaAgent
from harma.core.context import AgentContext
from harma.llm.provider import LLMResponse, ToolCall
from harma.tasks.conditions import ConditionWatcher
from harma.tasks.exceptions import (
    AutonomyPermissionError,
    DuplicateTaskError,
    ScopeViolationError,
    TaskConcurrencyLimitError,
    TaskError,
    TaskLockedError,
    TaskNotFoundError,
    TriggerValidationError,
)
from harma.tasks.executor import ScopedToolRegistry, TaskExecutor
from harma.tasks.locks import TaskLockManager
from harma.tasks.manager import TaskManager, get_task_manager, reset_task_manager, set_task_manager
from harma.tasks.models import (
    AutonomyLevel,
    Task,
    TaskExecutionHistory,
    TaskStatus,
    TaskTrigger,
    TriggerType,
)
from harma.tasks.notifications import NotificationManager
from harma.tasks.persistence import TaskStore
from harma.tasks.retry import ErrorCategory, ErrorClassifier, RetryPolicy
from harma.tasks.scheduler import TaskScheduler
from harma.tasks.tools import (
    CancelTaskTool,
    CreateTaskTool,
    DeleteTaskTool,
    GetTaskTool,
    ListTasksTool,
    PauseTaskTool,
    ResumeTaskTool,
    RunTaskNowTool,
    TaskHistoryTool,
    get_task_tools,
)
from harma.tasks.triggers import (
    Clock,
    FakeClock,
    calculate_next_run,
    get_timezone,
    validate_trigger,
)
from harma.tools.base import BaseTool, PermissionLevel, ToolResult


# ══════════════════════════════════════════════════════════════════════════════
# 1. Task Data Models, Triggers & Serialization
# ══════════════════════════════════════════════════════════════════════════════

class TestTaskModels(unittest.TestCase):
    """Tests for Task, TaskTrigger, TaskExecutionHistory models and serialization."""

    def test_task_creation_and_defaults(self) -> None:
        t = Task(name="Check Email", objective="Read new unread emails")
        self.assertTrue(t.id.startswith("task_"))
        self.assertEqual(t.status, TaskStatus.SCHEDULED)
        self.assertEqual(t.autonomy_level, AutonomyLevel.LEVEL_2_READ_ONLY)
        self.assertEqual(t.max_runtime_seconds, 300.0)
        self.assertEqual(t.max_steps, 50)
        self.assertEqual(t.max_retries, 3)

    def test_task_serialization_roundtrip(self) -> None:
        trigger = TaskTrigger(
            trigger_type=TriggerType.RECURRING,
            daily_time="08:30",
            weekly_days=[0, 1, 2, 3, 4],
        )
        task = Task(
            name="Morning Standup Brief",
            objective="Summarize yesterday's commits",
            trigger=trigger,
            autonomy_level=AutonomyLevel.LEVEL_3_LOW_RISK,
            allowed_tools=["git.log", "summary.write"],
            timezone="Asia/Kolkata",
            dry_run=True,
            idempotency_key="standup_brief_daily",
        )
        d = task.to_dict()
        restored = Task.from_dict(d)

        self.assertEqual(restored.id, task.id)
        self.assertEqual(restored.name, task.name)
        self.assertEqual(restored.objective, task.objective)
        self.assertEqual(restored.status, TaskStatus.SCHEDULED)
        self.assertEqual(restored.trigger.trigger_type, TriggerType.RECURRING)
        self.assertEqual(restored.trigger.daily_time, "08:30")
        self.assertEqual(restored.trigger.weekly_days, [0, 1, 2, 3, 4])
        self.assertEqual(restored.autonomy_level, AutonomyLevel.LEVEL_3_LOW_RISK)
        self.assertEqual(restored.allowed_tools, ["git.log", "summary.write"])
        self.assertEqual(restored.timezone, "Asia/Kolkata")
        self.assertTrue(restored.dry_run)
        self.assertEqual(restored.idempotency_key, "standup_brief_daily")

    def test_execution_history_serialization(self) -> None:
        hist = TaskExecutionHistory(
            execution_id="exec_123",
            task_id="task_abc",
            started_at=1700000000.0,
            completed_at=1700000005.0,
            status="success",
            summary="All 3 meetings summarized.",
            steps_taken=2,
            tools_used=["calendar.read"],
        )
        d = hist.to_dict()
        restored = TaskExecutionHistory.from_dict(d)
        self.assertEqual(restored.execution_id, "exec_123")
        self.assertEqual(restored.status, "success")
        self.assertEqual(restored.tools_used, ["calendar.read"])


# ══════════════════════════════════════════════════════════════════════════════
# 2. Timezone-Aware Scheduler & Controllable Clock
# ══════════════════════════════════════════════════════════════════════════════

class TestScheduler(unittest.IsolatedAsyncioTestCase):
    """Tests for timezone-aware scheduling, recurring triggers, and FakeClock."""

    def setUp(self) -> None:
        self.clock = FakeClock(initial_time=1700000000.0)  # Mon Nov 14 2023 ~22:13 UTC
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.store = TaskStore(db_path=f"{self.tmp_dir.name}/tasks.db")
        self.scheduler = TaskScheduler(store=self.store, clock=self.clock)

    def tearDown(self) -> None:
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def test_one_time_trigger_calculation(self) -> None:
        now = self.clock.now()
        target = now + 120.0
        trigger = TaskTrigger(trigger_type=TriggerType.ONE_TIME, run_at=target)

        next_run = calculate_next_run(trigger, now, tz_name="UTC")
        self.assertEqual(next_run, target)

        # In the past -> returns None (expired)
        expired_run = calculate_next_run(trigger, target + 1.0, tz_name="UTC")
        self.assertIsNone(expired_run)

    def test_interval_trigger_calculation(self) -> None:
        now = self.clock.now()
        trigger = TaskTrigger(trigger_type=TriggerType.INTERVAL, interval_seconds=3600.0)
        next_run = calculate_next_run(trigger, now)
        self.assertEqual(next_run, now + 3600.0)

    def test_recurring_daily_calculation(self) -> None:
        now = self.clock.now()
        trigger = TaskTrigger(trigger_type=TriggerType.RECURRING, daily_time="09:00")
        next_run = calculate_next_run(trigger, now, tz_name="UTC")
        self.assertIsNotNone(next_run)
        self.assertGreater(next_run, now)

    def test_recurring_weekly_calculation(self) -> None:
        now = self.clock.now()
        # Monday (0) and Wednesday (2)
        trigger = TaskTrigger(trigger_type=TriggerType.RECURRING, daily_time="10:00", weekly_days=[0, 2])
        next_run = calculate_next_run(trigger, now, tz_name="UTC")
        self.assertIsNotNone(next_run)
        self.assertGreater(next_run, now)

    async def test_scheduler_tick_dispatches_due_tasks(self) -> None:
        now = self.clock.now()
        # Create a task due 60s in future
        task = Task(
            name="Reminder",
            objective="Do laundry",
            trigger=TaskTrigger(trigger_type=TriggerType.ONE_TIME, run_at=now + 60.0),
        )
        self.scheduler.schedule(task)

        # Tick at current time -> not due yet
        dispatched_1 = await self.scheduler.tick()
        self.assertEqual(len(dispatched_1), 0)

        # Advance clock by 61s -> task is now due
        self.clock.advance(61.0)
        dispatched_2 = await self.scheduler.tick()
        self.assertEqual(len(dispatched_2), 1)
        self.assertEqual(dispatched_2[0].id, task.id)

    async def test_recurring_task_reschedules_after_tick(self) -> None:
        now = self.clock.now()
        task = Task(
            name="Periodic Check",
            objective="Check queue",
            trigger=TaskTrigger(trigger_type=TriggerType.INTERVAL, interval_seconds=300.0),
        )
        self.scheduler.schedule(task)

        # Advance to run time
        self.clock.advance(301.0)
        dispatched = await self.scheduler.tick()
        self.assertEqual(len(dispatched), 1)

        # Verify task was automatically rescheduled
        updated_task = self.store.get_task(task.id)
        self.assertIsNotNone(updated_task.next_run_at)
        self.assertGreater(updated_task.next_run_at, self.clock.now())


# ══════════════════════════════════════════════════════════════════════════════
# 3. Persistence & Restart Recovery
# ══════════════════════════════════════════════════════════════════════════════

class TestPersistenceAndRestart(unittest.TestCase):
    """Tests SQLite persistence and task restoration on process reboot."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = f"{self.tmp_dir.name}/tasks.db"
        self.store = TaskStore(db_path=self.db_path)

    def tearDown(self) -> None:
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def test_save_and_retrieve_task(self) -> None:
        task = Task(
            name="Backup Database",
            objective="Run nightly backup script",
            trigger=TaskTrigger(trigger_type=TriggerType.INTERVAL, interval_seconds=86400.0),
            autonomy_level=AutonomyLevel.LEVEL_3_LOW_RISK,
        )
        self.store.save_task(task)

        loaded = self.store.get_task(task.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.name, "Backup Database")
        self.assertEqual(loaded.autonomy_level, AutonomyLevel.LEVEL_3_LOW_RISK)

    def test_restart_recovery(self) -> None:
        # Create and schedule 2 tasks
        t1 = Task(name="Task 1", objective="Clean temp files", status=TaskStatus.SCHEDULED, next_run_at=time.time() + 100)
        t2 = Task(name="Task 2", objective="Sync logs", status=TaskStatus.SCHEDULED, next_run_at=time.time() + 200)
        t3 = Task(name="Task 3", objective="Old task", status=TaskStatus.COMPLETED)
        self.store.save_task(t1)
        self.store.save_task(t2)
        self.store.save_task(t3)

        # Simulate fresh startup: initialize new store and new manager on same DB
        new_store = TaskStore(db_path=self.db_path)
        new_manager = TaskManager(store=new_store)

        active = new_manager.list_tasks(status=TaskStatus.SCHEDULED)
        self.assertEqual(len(active), 2)
        active_ids = [t.id for t in active]
        self.assertIn(t1.id, active_ids)
        self.assertIn(t2.id, active_ids)

    def test_delete_and_list_tasks(self) -> None:
        t = Task(name="Temp Task", objective="One-off run")
        self.store.save_task(t)
        self.assertTrue(self.store.delete_task(t.id))
        self.assertIsNone(self.store.get_task(t.id))


# ══════════════════════════════════════════════════════════════════════════════
# 4. Task Executor, Agent Core Integration & Limits
# ══════════════════════════════════════════════════════════════════════════════

class TestTaskExecutor(unittest.IsolatedAsyncioTestCase):
    """Tests executing tasks through the existing Agent Core with safety bounds."""

    async def asyncSetUp(self) -> None:
        self.mock_llm = MagicMock()
        self.mock_llm.name = "mock-llm"
        self.mock_llm.complete = AsyncMock(
            return_value=LLMResponse(content="Task objective accomplished successfully.", tool_calls=[])
        )
        self.context = AgentContext(provider=self.mock_llm)
        self.executor = TaskExecutor(base_context=self.context)

    async def test_successful_task_execution(self) -> None:
        task = Task(name="Summarize", objective="Summarize today's agenda")
        history = await self.executor.execute(task)

        self.assertEqual(history.status, "success")
        self.assertEqual(history.summary, "Task objective accomplished successfully.")
        self.assertIsNotNone(history.completed_at)

    async def test_task_runtime_timeout_enforced(self) -> None:
        # LLM that hangs longer than max_runtime_seconds
        async def _slow_complete(*args, **kwargs):
            await asyncio.sleep(2.0)
            return LLMResponse(content="Done", tool_calls=[])

        self.mock_llm.complete = _slow_complete

        # 0.2 second limit
        task = Task(name="Slow Task", objective="Process huge data", max_runtime_seconds=0.2)
        history = await self.executor.execute(task)

        self.assertEqual(history.status, "timeout")
        self.assertIn("exceeded maximum duration", history.error)

    async def test_dry_run_mode_simulates_tools(self) -> None:
        scoped_reg = ScopedToolRegistry(
            base_registry=self.context.registry,
            allowed_tools=["mouse_click"],
            autonomy_level=AutonomyLevel.LEVEL_3_LOW_RISK,
            dry_run=True,
        )
        tool = scoped_reg.get("mouse_click")
        self.assertIsNotNone(tool)
        res = await tool.execute(x=100, y=200)
        self.assertTrue(res.success)
        self.assertTrue(res.data.get("dry_run"))


# ══════════════════════════════════════════════════════════════════════════════
# 5. Error Classification & Bounded Retries
# ══════════════════════════════════════════════════════════════════════════════

class TestRetryAndErrorClassification(unittest.TestCase):
    """Tests error categorization and exponential backoff calculations."""

    def test_classify_transient_vs_permanent_errors(self) -> None:
        self.assertEqual(ErrorClassifier.classify("Connection timed out after 15s"), ErrorCategory.TRANSIENT_ERROR)
        self.assertEqual(ErrorClassifier.classify("HTTP 429 Too Many Requests"), ErrorCategory.RATE_LIMIT)
        self.assertEqual(ErrorClassifier.classify("Unauthorized tool scope_violation"), ErrorCategory.PERMISSION_ERROR)
        self.assertEqual(ErrorClassifier.classify("Device is device_locked with PIN"), ErrorCategory.AUTHENTICATION_ERROR)
        self.assertEqual(ErrorClassifier.classify("User action required to confirm payment"), ErrorCategory.USER_ACTION_REQUIRED)
        self.assertEqual(ErrorClassifier.classify("Application Not Found"), ErrorCategory.PERMANENT_ERROR)

    def test_retry_policy_allows_transient_only(self) -> None:
        policy = RetryPolicy(max_attempts=3)

        # Transient error allows retry up to 3 times
        self.assertTrue(policy.should_retry(1, "network timeout"))
        self.assertTrue(policy.should_retry(2, "network timeout"))
        self.assertFalse(policy.should_retry(3, "network timeout"))

        # Permanent or permission errors never retry
        self.assertFalse(policy.should_retry(1, "scope_violation"))
        self.assertFalse(policy.should_retry(1, "device_locked"))
        self.assertFalse(policy.should_retry(1, "user action required"))

    def test_exponential_backoff_calculation(self) -> None:
        policy = RetryPolicy(initial_delay_seconds=2.0, backoff_factor=2.0, max_delay_seconds=60.0)
        self.assertEqual(policy.compute_backoff(1), 2.0)
        self.assertEqual(policy.compute_backoff(2), 4.0)
        self.assertEqual(policy.compute_backoff(3), 8.0)


# ══════════════════════════════════════════════════════════════════════════════
# 6. Autonomy Levels & Tool Allowlists
# ══════════════════════════════════════════════════════════════════════════════

class TestAutonomyAndAllowlists(unittest.TestCase):
    """Tests tool allowlists and autonomy level barriers."""

    def setUp(self) -> None:
        self.context = AgentContext(provider=MagicMock())

    def test_scope_violation_when_tool_not_in_allowlist(self) -> None:
        scoped = ScopedToolRegistry(
            base_registry=self.context.registry,
            allowed_tools=["get_current_time"],
            autonomy_level=AutonomyLevel.LEVEL_3_LOW_RISK,
        )

        # Allowed tool works
        self.assertIsNotNone(scoped.get("get_current_time"))

        # Unallowed tool raises ScopeViolationError
        with self.assertRaises(ScopeViolationError):
            scoped.get("mouse_click")

    def test_level1_reminder_blocks_action_tools(self) -> None:
        scoped = ScopedToolRegistry(
            base_registry=self.context.registry,
            allowed_tools=None,
            autonomy_level=AutonomyLevel.LEVEL_1_REMINDER,
        )
        with self.assertRaises(AutonomyPermissionError):
            scoped.get("mouse_click")

    def test_level2_read_only_blocks_sensitive_tools(self) -> None:
        scoped = ScopedToolRegistry(
            base_registry=self.context.registry,
            allowed_tools=None,
            autonomy_level=AutonomyLevel.LEVEL_2_READ_ONLY,
        )
        # SAFE tool allowed
        self.assertIsNotNone(scoped.get("get_current_time"))

        # SENSITIVE action tool blocked
        with self.assertRaises(AutonomyPermissionError):
            scoped.get("mouse_click")


# ══════════════════════════════════════════════════════════════════════════════
# 7. Concurrency & Per-Task Locking
# ══════════════════════════════════════════════════════════════════════════════

class TestConcurrencyAndLocks(unittest.IsolatedAsyncioTestCase):
    """Tests mutual exclusion on same task and global concurrency limits."""

    async def test_per_task_lock_prevents_duplicate_run(self) -> None:
        lock_mgr = TaskLockManager(max_concurrent_tasks=3)

        async with lock_mgr.task_execution_guard("task_1"):
            self.assertTrue(await lock_mgr.is_locked("task_1"))

            # Second concurrent attempt on task_1 must fail
            with self.assertRaises(TaskLockedError):
                async with lock_mgr.task_execution_guard("task_1"):
                    pass

        # Released after context exit
        self.assertFalse(await lock_mgr.is_locked("task_1"))

    async def test_global_concurrency_limit_enforced(self) -> None:
        lock_mgr = TaskLockManager(max_concurrent_tasks=2)

        async with lock_mgr.task_execution_guard("task_A"):
            async with lock_mgr.task_execution_guard("task_B"):
                self.assertEqual(await lock_mgr.running_count(), 2)

                # Third concurrent task exceeds limit
                with self.assertRaises(TaskConcurrencyLimitError):
                    async with lock_mgr.task_execution_guard("task_C"):
                        pass


# ══════════════════════════════════════════════════════════════════════════════
# 8. Conditional Tasks & Polling Limits
# ══════════════════════════════════════════════════════════════════════════════

class TestConditionalTasks(unittest.IsolatedAsyncioTestCase):
    """Tests ConditionWatcher with simulated triggers and custom evaluators."""

    async def test_condition_evaluation_triggers_when_met(self) -> None:
        watcher = ConditionWatcher()

        # Custom evaluator for stock price condition
        price = 150.0
        async def _check_stock(query: str) -> bool:
            return price < 100.0

        watcher.register_evaluator("stock_price", _check_stock)

        task = Task(
            name="Stock Watcher",
            objective="Alert on drop",
            trigger=TaskTrigger(trigger_type=TriggerType.CONDITIONAL, condition_query="stock_price_aapl"),
        )

        # Condition false initially
        self.assertFalse(await watcher.evaluate(task))

        # Price drops
        price = 95.0
        self.assertTrue(await watcher.evaluate(task))


# ══════════════════════════════════════════════════════════════════════════════
# 9. Notifications & Quiet Hours
# ══════════════════════════════════════════════════════════════════════════════

class TestNotificationsAndQuietHours(unittest.IsolatedAsyncioTestCase):
    """Tests notification dispatch and quiet hours suppression."""

    def test_quiet_hours_detection(self) -> None:
        # Mock clock at 23:30 (inside 22:00-07:00 window)
        clock = FakeClock()
        # Set epoch corresponding to 23:30 UTC
        tz = get_timezone("UTC")
        clock.set_time(1700004600.0)  # arbitrary baseline
        # Create a manager with 22:00-07:00 quiet hours
        mgr = NotificationManager(quiet_hours_enabled=True, quiet_hours_start="22:00", quiet_hours_end="07:00", clock=clock)

        # Force datetime to 23:30
        with patch.object(clock, "datetime", return_value=clock.datetime().replace(hour=23, minute=30)):
            self.assertTrue(mgr.is_quiet_hours("UTC"))

        # Force datetime to 14:00 (outside quiet hours)
        with patch.object(clock, "datetime", return_value=clock.datetime().replace(hour=14, minute=0)):
            self.assertFalse(mgr.is_quiet_hours("UTC"))

    async def test_notification_delivery_to_listeners(self) -> None:
        mgr = NotificationManager(quiet_hours_enabled=False)
        received = []

        def _listener(event: str, task: Task, msg: str):
            received.append((event, task.id, msg))

        mgr.add_listener(_listener)

        task = Task(name="Calendar Alert", objective="Check meetings")
        await mgr.notify(event="completed", task=task, message="Calendar check done.")

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0], ("completed", task.id, "Calendar check done."))


# ══════════════════════════════════════════════════════════════════════════════
# 10. Security, Prompt-Injection & Scope Integrity
# ══════════════════════════════════════════════════════════════════════════════

class TestTaskSecurity(unittest.TestCase):
    """Tests security bounds preventing prompt-injection scope expansion."""

    def test_cannot_silently_expand_allowed_tools(self) -> None:
        scoped = ScopedToolRegistry(
            base_registry=AgentContext(provider=MagicMock()).registry,
            allowed_tools=["get_current_time"],
            autonomy_level=AutonomyLevel.LEVEL_2_READ_ONLY,
        )

        # Malicious tool injected in query is rejected
        with self.assertRaises(ScopeViolationError):
            scoped.get("android.tap")

        with self.assertRaises(ScopeViolationError):
            scoped.get("mouse_click")

    def test_duplicate_task_detection_raises_error(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        try:
            store = TaskStore(db_path=f"{tmp_dir.name}/tasks.db")
            mgr = TaskManager(store=store)

            trigger = TaskTrigger(trigger_type=TriggerType.INTERVAL, interval_seconds=3600.0)

            # Create first task
            asyncio.run(mgr.create_task(name="Sync", objective="Sync repo updates", trigger=trigger))

            # Attempt to create duplicate task with identical objective and trigger
            with self.assertRaises(DuplicateTaskError):
                asyncio.run(mgr.create_task(name="Sync 2", objective="Sync repo updates", trigger=trigger))
        finally:
            try:
                tmp_dir.cleanup()
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════════════
# 11. Section 49 Real-World Integration Scenarios (Tests 1–6)
# ══════════════════════════════════════════════════════════════════════════════

class TestSection49Scenarios(unittest.IsolatedAsyncioTestCase):
    """
    Tests covering all 6 practical scenarios specified in Section 49:
      Test 1 (Reminder): "Remind me in 2 minutes to test Harma"
      Test 2 (Recurring): "Every day at 8 AM, check my calendar"
      Test 3 (Browser): "Every morning check this page and tell me if it changed"
      Test 4 (Voice): Voice command creates scheduled task
      Test 5 (Android): Android reminder task created through agent
      Test 6 (Cancellation): "Cancel my morning calendar task"
    """

    async def asyncSetUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.store = TaskStore(db_path=f"{self.tmp_dir.name}/tasks.db")
        self.clock = FakeClock(initial_time=1700000000.0)

        self.mock_llm = MagicMock()
        self.mock_llm.name = "mock-llm"
        self.mock_llm.complete = AsyncMock(
            return_value=LLMResponse(content="Task executed successfully.", tool_calls=[])
        )
        self.context = AgentContext(provider=self.mock_llm)
        self.executor = TaskExecutor(base_context=self.context)

        self.manager = TaskManager(
            store=self.store,
            clock=self.clock,
            executor=self.executor,
        )
        set_task_manager(self.manager)

    async def asyncTearDown(self) -> None:
        reset_task_manager()
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    async def test_scenario_1_reminder_task(self) -> None:
        # "Remind me in 2 minutes to test Harma"
        now = self.clock.now()
        trigger = TaskTrigger(trigger_type=TriggerType.ONE_TIME, run_at=now + 120.0)
        task = await self.manager.create_task(
            name="Test Reminder",
            objective="Remind user to test Harma",
            trigger=trigger,
            autonomy_level=AutonomyLevel.LEVEL_1_REMINDER,
        )
        self.assertEqual(task.status, TaskStatus.SCHEDULED)
        self.assertEqual(task.next_run_at, now + 120.0)

        # Advance clock by 2 minutes
        self.clock.advance(121.0)
        dispatched = await self.manager.scheduler.tick()
        self.assertEqual(len(dispatched), 1)

    async def test_scenario_2_recurring_calendar_task(self) -> None:
        # "Every day at 8 AM, check my calendar"
        trigger = TaskTrigger(trigger_type=TriggerType.RECURRING, daily_time="08:00")
        task = await self.manager.create_task(
            name="Daily Calendar Brief",
            objective="Check today's calendar and summarize meetings",
            trigger=trigger,
            autonomy_level=AutonomyLevel.LEVEL_2_READ_ONLY,
            timezone="UTC",
        )
        self.assertEqual(task.status, TaskStatus.SCHEDULED)
        self.assertIsNotNone(task.next_run_at)

        # Persisted in DB
        loaded = self.store.get_task(task.id)
        self.assertEqual(loaded.trigger.daily_time, "08:00")

    async def test_scenario_3_conditional_browser_task(self) -> None:
        # "Every morning check this page and tell me if it changed"
        trigger = TaskTrigger(
            trigger_type=TriggerType.CONDITIONAL,
            condition_query="page_price_changed_https://example.com",
            condition_poll_interval=120.0,
        )
        task = await self.manager.create_task(
            name="Price Monitor",
            objective="Check if product price dropped below $100",
            trigger=trigger,
        )
        self.assertEqual(task.status, TaskStatus.SCHEDULED)

    async def test_scenario_4_voice_scheduled_task(self) -> None:
        # Voice command: "Hey Harma, remind me tomorrow at 9 AM."
        # Simulated agent turn executing tasks.create tool
        tool = CreateTaskTool(self.manager)
        res = await tool.execute(
            name="Morning Reminder",
            objective="Review roadmap",
            trigger_type="one_time",
            run_at=self.clock.now() + 86400.0,
        )
        self.assertTrue(res.success)
        self.assertIn("created and scheduled", res.output)

    async def test_scenario_5_android_reminder_task(self) -> None:
        # "Hey Harma, remind me at 7 PM to charge my phone."
        tool = CreateTaskTool(self.manager)
        res = await tool.execute(
            name="Charge Phone",
            objective="Remind user to charge Android phone",
            trigger_type="one_time",
            run_at=self.clock.now() + 3600.0,
            allowed_tools=["android.device_status"],
        )
        self.assertTrue(res.success)
        task_id = res.data["id"]
        created = self.manager.get_task(task_id)
        self.assertEqual(created.allowed_tools, ["android.device_status"])

    async def test_scenario_6_cancellation(self) -> None:
        # Create task then cancel it
        task = await self.manager.create_task(
            name="Weekly Report",
            objective="Prepare metrics report",
            trigger=TaskTrigger(trigger_type=TriggerType.INTERVAL, interval_seconds=86400.0),
        )
        self.assertEqual(task.status, TaskStatus.SCHEDULED)

        cancelled = self.manager.cancel_task(task.id)
        self.assertEqual(cancelled.status, TaskStatus.CANCELLED)
        self.assertIsNone(cancelled.next_run_at)


# ══════════════════════════════════════════════════════════════════════════════
# 12. Task Management Tools, CLI & Emergency Stop
# ══════════════════════════════════════════════════════════════════════════════

class TestTaskToolsAndControls(unittest.IsolatedAsyncioTestCase):
    """Tests all registered task tools, dashboard stats, and emergency stop."""

    async def asyncSetUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.store = TaskStore(db_path=f"{self.tmp_dir.name}/tasks.db")
        self.clock = FakeClock(initial_time=1700000000.0)
        self.manager = TaskManager(store=self.store, clock=self.clock)
        self.tools = {t.name: t for t in get_task_tools(self.manager)}

    async def asyncTearDown(self) -> None:
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def test_task_tools_registered(self) -> None:
        expected = [
            "tasks.create",
            "tasks.get",
            "tasks.list",
            "tasks.pause",
            "tasks.resume",
            "tasks.cancel",
            "tasks.run_now",
            "tasks.history",
            "tasks.delete",
        ]
        for name in expected:
            self.assertIn(name, self.tools)

    async def test_task_tools_crud_flow(self) -> None:
        # 1. Create
        create_res = await self.tools["tasks.create"].execute(
            name="Check RSS",
            objective="Fetch tech news feed",
            trigger_type="interval",
            interval_seconds=1800.0,
        )
        self.assertTrue(create_res.success)
        task_id = create_res.data["id"]

        # 2. Get
        get_res = await self.tools["tasks.get"].execute(task_id=task_id)
        self.assertTrue(get_res.success)
        self.assertIn("Check RSS", get_res.output)

        # 3. List
        list_res = await self.tools["tasks.list"].execute()
        self.assertTrue(list_res.success)
        self.assertIn("Check RSS", list_res.output)

        # 4. Pause
        pause_res = await self.tools["tasks.pause"].execute(task_id=task_id)
        self.assertTrue(pause_res.success)
        self.assertEqual(self.manager.get_task(task_id).status, TaskStatus.PAUSED)

        # 5. Resume
        resume_res = await self.tools["tasks.resume"].execute(task_id=task_id)
        self.assertTrue(resume_res.success)
        self.assertEqual(self.manager.get_task(task_id).status, TaskStatus.SCHEDULED)

        # 6. Delete
        del_res = await self.tools["tasks.delete"].execute(task_id=task_id)
        self.assertTrue(del_res.success)
        with self.assertRaises(TaskNotFoundError):
            self.manager.get_task(task_id)

    async def test_emergency_stop_all(self) -> None:
        # Create 3 scheduled tasks
        for i in range(3):
            await self.manager.create_task(
                name=f"Task {i}",
                objective=f"Objective {i}",
                trigger=TaskTrigger(trigger_type=TriggerType.INTERVAL, interval_seconds=3600.0),
            )

        self.assertEqual(len(self.manager.list_tasks(status=TaskStatus.SCHEDULED)), 3)

        # Emergency stop
        stopped_count = await self.manager.stop_all()
        self.assertEqual(stopped_count, 3)
        self.assertEqual(len(self.manager.list_tasks(status=TaskStatus.SCHEDULED)), 0)
        self.assertEqual(len(self.manager.list_tasks(status=TaskStatus.PAUSED)), 3)

    def test_dashboard_stats(self) -> None:
        asyncio.run(
            self.manager.create_task(
                name="Stats Task",
                objective="Test statistics",
                trigger=TaskTrigger(trigger_type=TriggerType.INTERVAL, interval_seconds=100.0),
            )
        )
        st = self.manager.stats()
        self.assertEqual(st["total"], 1)
        self.assertIn("scheduled", st["by_status"])
        self.assertIsNotNone(st["next_execution"])


if __name__ == "__main__":
    unittest.main()
