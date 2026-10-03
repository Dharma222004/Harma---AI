"""
Harma Task Persistence

SQLite-backed persistent store for tasks and execution history.
Ensures scheduled tasks survive process restarts.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from pathlib import Path
from typing import Generator, Optional

from harma.config.logging_config import get_logger
from harma.config.settings import ROOT_DIR
from harma.tasks.exceptions import TaskNotFoundError
from harma.tasks.models import Task, TaskExecutionHistory, TaskStatus

log = get_logger(__name__)

DEFAULT_TASK_DB_PATH = str(ROOT_DIR / "data" / "harma_tasks.db")


class TaskStore:
    """
    Thread-safe SQLite storage for tasks and execution histories.
    """

    def __init__(self, db_path: str = DEFAULT_TASK_DB_PATH) -> None:
        self.db_path = db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextlib.contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def close(self) -> None:
        """Close any store handles if needed."""
        pass

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trigger_json TEXT NOT NULL,
                    autonomy_level TEXT NOT NULL,
                    allowed_tools_json TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    next_run_at REAL,
                    last_run_at REAL,
                    execution_count INTEGER NOT NULL DEFAULT 0,
                    max_runtime_seconds REAL NOT NULL DEFAULT 300.0,
                    max_steps INTEGER NOT NULL DEFAULT 50,
                    max_retries INTEGER NOT NULL DEFAULT 3,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    notification_channels_json TEXT NOT NULL,
                    dry_run INTEGER NOT NULL DEFAULT 0,
                    idempotency_key TEXT,
                    metadata_json TEXT
                );

                CREATE TABLE IF NOT EXISTS task_executions (
                    execution_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    completed_at REAL,
                    status TEXT NOT NULL,
                    summary TEXT,
                    error TEXT,
                    steps_taken INTEGER NOT NULL DEFAULT 0,
                    tools_used_json TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status);
                CREATE INDEX IF NOT EXISTS idx_tasks_next_run ON tasks (next_run_at);
                CREATE INDEX IF NOT EXISTS idx_task_executions_task ON task_executions (task_id);
                """
            )

    def save_task(self, task: Task) -> None:
        """Insert or update a task."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO tasks (
                    id, name, objective, status, trigger_json, autonomy_level,
                    allowed_tools_json, timezone, created_at, updated_at,
                    next_run_at, last_run_at, execution_count, max_runtime_seconds,
                    max_steps, max_retries, retry_count, last_error,
                    notification_channels_json, dry_run, idempotency_key, metadata_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?
                )
                """,
                (
                    task.id,
                    task.name,
                    task.objective,
                    task.status.value,
                    json.dumps(task.trigger.to_dict()),
                    task.autonomy_level.value,
                    json.dumps(task.allowed_tools),
                    task.timezone,
                    task.created_at,
                    task.updated_at,
                    task.next_run_at,
                    task.last_run_at,
                    task.execution_count,
                    task.max_runtime_seconds,
                    task.max_steps,
                    task.max_retries,
                    task.retry_count,
                    task.last_error,
                    json.dumps(task.notification_channels),
                    1 if task.dry_run else 0,
                    task.idempotency_key,
                    json.dumps(task.metadata),
                ),
            )

    def get_task(self, task_id: str) -> Optional[Task]:
        """Fetch task by ID, or None if not found."""
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_task(row)

    def list_tasks(self, status: Optional[TaskStatus] = None) -> list[Task]:
        """List tasks optionally filtered by status."""
        with self._get_connection() as conn:
            if status is not None:
                cur = conn.execute(
                    "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC",
                    (status.value,),
                )
            else:
                cur = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC")
            return [self._row_to_task(row) for row in cur.fetchall()]

    def delete_task(self, task_id: str) -> bool:
        """Delete task by ID."""
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            return cur.rowcount > 0

    def save_execution(self, history: TaskExecutionHistory) -> None:
        """Record an execution run."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO task_executions (
                    execution_id, task_id, started_at, completed_at,
                    status, summary, error, steps_taken, tools_used_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    history.execution_id,
                    history.task_id,
                    history.started_at,
                    history.completed_at,
                    history.status,
                    history.summary,
                    history.error,
                    history.steps_taken,
                    json.dumps(history.tools_used),
                ),
            )

    def list_executions(
        self, task_id: Optional[str] = None, limit: int = 50
    ) -> list[TaskExecutionHistory]:
        """List recent execution histories."""
        with self._get_connection() as conn:
            if task_id:
                cur = conn.execute(
                    "SELECT * FROM task_executions WHERE task_id = ? ORDER BY started_at DESC LIMIT ?",
                    (task_id, limit),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM task_executions ORDER BY started_at DESC LIMIT ?",
                    (limit,),
                )
            return [self._row_to_execution(row) for row in cur.fetchall()]

    def clear_all(self) -> None:
        """Clear all tasks and histories (used in tests)."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM task_executions")
            conn.execute("DELETE FROM tasks")

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        data = dict(row)
        data["trigger"] = json.loads(data["trigger_json"])
        data["allowed_tools"] = json.loads(data["allowed_tools_json"])
        data["notification_channels"] = json.loads(data["notification_channels_json"])
        data["metadata"] = json.loads(data["metadata_json"] or "{}")
        data["dry_run"] = bool(data["dry_run"])
        return Task.from_dict(data)

    def _row_to_execution(self, row: sqlite3.Row) -> TaskExecutionHistory:
        data = dict(row)
        data["tools_used"] = json.loads(data["tools_used_json"] or "[]")
        return TaskExecutionHistory.from_dict(data)
