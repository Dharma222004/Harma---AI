"""
Harma Control Center & API Models

Defines the global runtime state, normalized event models, confirmation
structures, and audit logging entries.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class AgentStatus(str, Enum):
    """Runtime execution status of HarmaAgent."""
    IDLE = "idle"
    THINKING = "thinking"
    EXECUTING = "executing"
    PAUSED = "paused"
    ERROR = "error"
    EMERGENCY_STOPPED = "emergency_stopped"


class EventSeverity(str, Enum):
    """Event severity levels."""
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    CONFIRMATION = "confirmation"


@dataclass
class HarmaEvent:
    """
    Normalized event model broadcast to UI and WebSocket subscribers.
    """
    event_type: str
    source: str = "system"
    severity: EventSeverity = EventSeverity.INFO
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "source": self.source,
            "severity": self.severity.value,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }


@dataclass
class ConfirmationRequest:
    """User confirmation card data model for consequential/sensitive actions."""
    action: str
    target: str
    parameters: dict[str, Any] = field(default_factory=dict)
    consequence: str = "Potential external modification"
    service: str = "local"
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: str = "pending"  # pending | approved | rejected
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "target": self.target,
            "parameters": self.parameters,
            "consequence": self.consequence,
            "service": self.service,
            "status": self.status,
            "timestamp": self.timestamp,
        }


@dataclass
class AuditEntry:
    """Immutable audit trail entry for verified and consequential actions."""
    action: str
    target: str
    parameters: dict[str, Any] = field(default_factory=dict)
    consequence: str = ""
    user_approved: bool = True
    verification_status: str = "VERIFIED"
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "action": self.action,
            "target": self.target,
            "parameters": self.parameters,
            "consequence": self.consequence,
            "user_approved": self.user_approved,
            "verification_status": self.verification_status,
        }


@dataclass
class HarmaRuntimeState:
    """
    Read-only unified application runtime state model.
    """
    agent_status: AgentStatus = AgentStatus.IDLE
    current_request: str = ""
    current_plan: Optional[dict[str, Any]] = None
    current_step: Optional[dict[str, Any]] = None
    active_task: Optional[dict[str, Any]] = None
    pending_confirmation: Optional[dict[str, Any]] = None
    voice_state: str = "ready"  # ready | listening | processing | speaking | disabled
    browser_state: dict[str, Any] = field(default_factory=lambda: {"active": False, "url": "", "title": ""})
    computer_state: dict[str, Any] = field(default_factory=lambda: {"active_window": "Desktop", "screen": "1920x1080"})
    android_state: dict[str, Any] = field(default_factory=lambda: {"connected": False, "device": "none"})
    integrations: list[dict[str, Any]] = field(default_factory=list)
    memory_state: dict[str, Any] = field(default_factory=lambda: {"total": 0, "active": 0})
    llm_state: dict[str, Any] = field(default_factory=lambda: {"provider": "NVIDIA", "model": "", "status": "Connected", "latency_ms": 0.0})
    autonomy_level: str = "supervised"  # manual | assisted | supervised | autonomous
    is_emergency_stopped: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_status": self.agent_status.value,
            "current_request": self.current_request,
            "current_plan": self.current_plan,
            "current_step": self.current_step,
            "active_task": self.active_task,
            "pending_confirmation": self.pending_confirmation,
            "voice_state": self.voice_state,
            "browser_state": self.browser_state,
            "computer_state": self.computer_state,
            "android_state": self.android_state,
            "integrations": self.integrations,
            "memory_state": self.memory_state,
            "llm_state": self.llm_state,
            "autonomy_level": self.autonomy_level,
            "is_emergency_stopped": self.is_emergency_stopped,
            "timestamp": self.timestamp,
        }
