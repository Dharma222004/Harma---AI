"""
Harma Short-Term Memory

Maintains the active conversation and task state.
This is the in-process memory that lives for the duration of a session.

Responsibilities:
  • Store conversation messages (user / assistant / tool).
  • Track the current task and its state.
  • Provide summarised context when the history exceeds token limits.
  • Clear on session end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from harma.config.logging_config import get_logger
from harma.config.settings import config
from harma.llm.provider import Message, Role, ToolCall, ToolResult

log = get_logger(__name__)


@dataclass
class TaskState:
    """Tracks the state of the currently executing multi-step task."""

    task_id: str
    description: str
    started_at: datetime = field(default_factory=datetime.now)
    steps_completed: list[str] = field(default_factory=list)
    current_step: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    is_complete: bool = False
    result: str = ""


class ShortTermMemory:
    """
    Session-scoped in-memory store.

    Provides the conversation history in Harma's Message format so the
    LLM provider can consume it directly without any conversion.
    """

    def __init__(self) -> None:
        self._messages: list[Message] = []
        self._max_messages = config.memory.short_term_max_messages
        self._current_task: Optional[TaskState] = None
        self._active_application: Optional[str] = None

    # ── Conversation ──────────────────────────────────────────────────────────

    def add_user_message(self, content: str) -> None:
        self._messages.append(Message(role=Role.USER, content=content))
        log.debug("Memory: +user message (%d chars)", len(content))
        self._trim()

    def add_assistant_message(
        self,
        content: str,
        tool_calls: Optional[list[ToolCall]] = None,
    ) -> None:
        self._messages.append(
            Message(
                role=Role.ASSISTANT,
                content=content,
                tool_calls=tool_calls or [],
            )
        )
        log.debug("Memory: +assistant message (%d chars, %d tool_calls)",
                  len(content), len(tool_calls or []))
        self._trim()

    def add_tool_results(self, results: list[ToolResult]) -> None:
        self._messages.append(
            Message(role=Role.TOOL, tool_results=results)
        )
        log.debug("Memory: +tool results (count=%d)", len(results))
        self._trim()

    def get_messages(self) -> list[Message]:
        """
        Return the conversation history. For extended multi-step tasks,
        older intermediate tool outputs are compactly pruned to preserve
        LLM context budget and latency while keeping recent observations intact.
        """
        if len(self._messages) <= 6:
            return list(self._messages)

        compacted: list[Message] = []
        recent_threshold = max(0, len(self._messages) - 4)
        for idx, m in enumerate(self._messages):
            if idx < recent_threshold and m.role == Role.TOOL and m.tool_results:
                compact_results = []
                for tr in m.tool_results:
                    content = tr.content or ""
                    if len(content) > 500:
                        content = content[:500] + "... [prior step output summary]"
                    compact_results.append(ToolResult(
                        tool_call_id=tr.tool_call_id,
                        name=tr.name,
                        content=content,
                        is_error=tr.is_error,
                    ))
                compacted.append(Message(role=Role.TOOL, tool_results=compact_results))
            else:
                compacted.append(m)
        return compacted

    def clear(self) -> None:
        """Clear conversation history (e.g. on new session)."""
        self._messages.clear()
        self._current_task = None
        log.info("Short-term memory cleared.")

    def _trim(self) -> None:
        """Keep memory within max_messages limit."""
        while len(self._messages) > self._max_messages:
            # Remove oldest non-system message
            self._messages.pop(0)

    # ── Task context ──────────────────────────────────────────────────────────

    def start_task(self, task_id: str, description: str) -> TaskState:
        self._current_task = TaskState(task_id=task_id, description=description)
        log.info("Task started: [%s] %s", task_id, description)
        return self._current_task

    def update_task(self, step: str, context: Optional[dict] = None) -> None:
        if self._current_task:
            self._current_task.steps_completed.append(step)
            self._current_task.current_step = step
            if context:
                self._current_task.context.update(context)

    def complete_task(self, result: str) -> None:
        if self._current_task:
            self._current_task.is_complete = True
            self._current_task.result = result
            log.info("Task complete: %s", result)

    @property
    def current_task(self) -> Optional[TaskState]:
        return self._current_task

    # ── Application context ───────────────────────────────────────────────────

    @property
    def active_application(self) -> Optional[str]:
        return self._active_application

    @active_application.setter
    def active_application(self, app: str) -> None:
        self._active_application = app
        log.debug("Active application set to: %s", app)

    # ── Debug ─────────────────────────────────────────────────────────────────

    def summary(self) -> str:
        lines = [f"Messages in memory: {len(self._messages)}"]
        if self._current_task:
            lines.append(f"Current task: {self._current_task.description}")
        if self._active_application:
            lines.append(f"Active app: {self._active_application}")
        return "\n".join(lines)
