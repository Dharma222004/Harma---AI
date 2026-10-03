"""
Harma Long-Term Memory — Data Models — Phase 5

Strongly-typed memory objects. No ad-hoc dictionaries.
Every memory written to the database passes through these models.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


from harma.memory.exceptions import MemoryValidationError


# ─────────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────────

class MemoryType(str, Enum):
    """Classifies what kind of knowledge a memory represents."""
    SEMANTIC    = "semantic"    # stable facts: language preference, project name
    EPISODIC    = "episodic"    # significant past events worth remembering
    PREFERENCE  = "preference"  # explicit user preferences
    PROJECT     = "project"     # project-specific context
    WORKFLOW    = "workflow"    # reusable task workflows / procedures


class MemorySource(str, Enum):
    """Tracks where a memory originated."""
    EXPLICIT_USER   = "explicit_user"   # "Remember that…" / "My project is…"
    USER_CORRECTION = "user_correction" # "I don't use Python anymore…"
    CONVERSATION    = "conversation"    # inferred from conversation flow
    TOOL_RESULT     = "tool_result"     # extracted from a tool execution result
    PROJECT_CONTEXT = "project_context" # derived from project structure
    SYSTEM          = "system"          # Harma-generated bookkeeping
    IMPORTED        = "imported"        # externally imported


class MemorySensitivity(str, Enum):
    """Privacy/sensitivity classification."""
    NORMAL          = "normal"          # safe to use freely in context
    SENSITIVE       = "sensitive"       # use carefully, label in context
    HIGH_SENSITIVITY = "high_sensitivity"  # never auto-retrieved; require explicit ask


class MemoryStatus(str, Enum):
    """Lifecycle state of a memory."""
    ACTIVE    = "active"    # normal — retrieved and used
    SUPERSEDED = "superseded" # replaced by a newer/correcting memory
    ARCHIVED  = "archived"  # retained for audit but not actively retrieved
    DELETED   = "deleted"   # soft-deleted; not returned in queries


# ─────────────────────────────────────────────────────────────────────────────
# Core Memory Object
# ─────────────────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class Memory:
    """
    The fundamental unit of long-term memory in Harma.

    All memories stored in the database are instances of this class.
    Never store raw dicts in the persistence layer.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    id: str = field(default_factory=_new_id)

    # ── Content ───────────────────────────────────────────────────────────────
    content: str = ""
    """Human-readable memory content. This is what gets injected into context."""

    summary: str = ""
    """Optional one-line summary for listing / display."""

    # ── Classification ────────────────────────────────────────────────────────
    memory_type: MemoryType = MemoryType.SEMANTIC
    source: MemorySource = MemorySource.EXPLICIT_USER
    sensitivity: MemorySensitivity = MemorySensitivity.NORMAL
    status: MemoryStatus = MemoryStatus.ACTIVE

    # ── Quality scores ────────────────────────────────────────────────────────
    importance: float = 0.8
    """0.0 = disposable → 1.0 = critical. Affects retention and retrieval ranking."""

    confidence: float = 1.0
    """0.0 = unreliable → 1.0 = explicitly stated. Inferred memories have lower confidence."""

    # ── Organisation ─────────────────────────────────────────────────────────
    tags: list[str] = field(default_factory=list)
    """Free-form tags for filtering (e.g. ['python', 'harma', 'project'])."""

    project_id: Optional[str] = None
    """Link to a project scope. None = global / personal preference."""

    supersedes_id: Optional[str] = None
    """If this memory corrects/replaces another, set that memory's ID here."""

    # ── Lifecycle timestamps ──────────────────────────────────────────────────
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    last_accessed_at: datetime = field(default_factory=_now)
    access_count: int = 0

    # ── Extra metadata ────────────────────────────────────────────────────────
    metadata: dict[str, Any] = field(default_factory=dict)
    """Provider-specific or tool-specific metadata. Treated as DATA, never instructions."""

    # ── Embedding ─────────────────────────────────────────────────────────────
    embedding: Optional[list[float]] = None
    """Semantic embedding vector, if available. None = use keyword search."""

    def __post_init__(self) -> None:
        if not self.content or not self.content.strip():
            raise MemoryValidationError("Memory content cannot be empty.")
        if not (0.0 <= self.importance <= 1.0):
            raise MemoryValidationError(f"importance must be between 0.0 and 1.0, got {self.importance}")
        if not (0.0 <= self.confidence <= 1.0):
            raise MemoryValidationError(f"confidence must be between 0.0 and 1.0, got {self.confidence}")

    @property
    def replaces(self) -> Optional[str]:
        return self.supersedes_id

    @replaces.setter
    def replaces(self, val: Optional[str]) -> None:
        self.supersedes_id = val

    @property
    def superseded_by(self) -> Optional[str]:
        return self.metadata.get("superseded_by")

    @superseded_by.setter
    def superseded_by(self, val: Optional[str]) -> None:
        if val:
            self.metadata["superseded_by"] = val

    # ── Computed helpers ──────────────────────────────────────────────────────

    def is_active(self) -> bool:
        return self.status == MemoryStatus.ACTIVE

    def is_sensitive(self) -> bool:
        return self.sensitivity in (
            MemorySensitivity.SENSITIVE,
            MemorySensitivity.HIGH_SENSITIVITY,
        )

    def touch(self) -> None:
        """Update access tracking fields."""
        self.last_accessed_at = _now()
        self.access_count += 1

    def display_label(self) -> str:
        """Short human label for listing."""
        short = (self.summary or self.content)[:80]
        return f"[{self.memory_type.value}] {short}"

    def recency_days(self) -> float:
        """Days since this memory was created."""
        delta = _now() - self.created_at
        return delta.total_seconds() / 86400

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a flat dict (for storage and logging)."""
        return {
            "id": self.id,
            "content": self.content,
            "summary": self.summary,
            "memory_type": self.memory_type.value,
            "source": self.source.value,
            "sensitivity": self.sensitivity.value,
            "status": self.status.value,
            "importance": self.importance,
            "confidence": self.confidence,
            "tags": ",".join(self.tags),
            "project_id": self.project_id or "",
            "supersedes_id": self.supersedes_id or "",
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_accessed_at": self.last_accessed_at.isoformat(),
            "access_count": self.access_count,
            "metadata": str(self.metadata),
        }

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "Memory":
        """Deserialize from a storage row."""
        import json

        def _dt(s: str) -> datetime:
            try:
                return datetime.fromisoformat(s)
            except Exception:
                return _now()

        def _tags(s: str) -> list[str]:
            return [t.strip() for t in s.split(",") if t.strip()] if s else []

        def _meta(s: str) -> dict:
            try:
                return json.loads(s)
            except Exception:
                return {}

        return cls(
            id=row.get("id", _new_id()),
            content=row.get("content", ""),
            summary=row.get("summary", ""),
            memory_type=MemoryType(row.get("memory_type", "semantic")),
            source=MemorySource(row.get("source", "system")),
            sensitivity=MemorySensitivity(row.get("sensitivity", "normal")),
            status=MemoryStatus(row.get("status", "active")),
            importance=float(row.get("importance", 0.5)),
            confidence=float(row.get("confidence", 1.0)),
            tags=_tags(row.get("tags", "")),
            project_id=row.get("project_id") or None,
            supersedes_id=row.get("supersedes_id") or None,
            created_at=_dt(row.get("created_at", "")),
            updated_at=_dt(row.get("updated_at", "")),
            last_accessed_at=_dt(row.get("last_accessed_at", "")),
            access_count=int(row.get("access_count", 0)),
            metadata=_meta(row.get("metadata", "{}")),
        )

    def __repr__(self) -> str:
        return (
            f"Memory(id={self.id[:8]!r} type={self.memory_type.value!r} "
            f"importance={self.importance:.1f} confidence={self.confidence:.1f} "
            f"content={self.content[:40]!r})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Search Query
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MemoryQuery:
    """Parameters for a memory search operation."""
    text: str = ""                          # keyword / semantic query
    memory_types: list[MemoryType] = field(default_factory=list)
    project_id: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    min_importance: float = 0.0
    min_confidence: float = 0.0
    status_filter: list[MemoryStatus] = field(
        default_factory=lambda: [MemoryStatus.ACTIVE]
    )
    top_k: int = 8
    include_sensitive: bool = False         # only include HIGH_SENSITIVITY if True

    @property
    def status(self) -> MemoryStatus:
        return self.status_filter[0] if self.status_filter else MemoryStatus.ACTIVE

    @status.setter
    def status(self, val: MemoryStatus) -> None:
        self.status_filter = [val]


# ─────────────────────────────────────────────────────────────────────────────
# Search Result
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MemorySearchResult:
    """A memory matched by a search query, with its relevance score."""
    memory: Memory
    score: float = 0.0
    """Combined relevance score (0.0–1.0). Higher = more relevant."""

    def __lt__(self, other: "MemorySearchResult") -> bool:
        return self.score < other.score


# ─────────────────────────────────────────────────────────────────────────────
# Extraction Candidate
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MemoryCandidate:
    """
    A memory that has been extracted from conversation but not yet validated/saved.
    Used in the extraction → validation → persist pipeline.
    """
    content: str
    memory_type: MemoryType
    source: MemorySource
    importance: float = 0.5
    confidence: float = 0.8
    tags: list[str] = field(default_factory=list)
    project_id: Optional[str] = None
    sensitivity: MemorySensitivity = MemorySensitivity.NORMAL

    def to_memory(self) -> Memory:
        return Memory(
            content=self.content,
            summary=self.content[:80],
            memory_type=self.memory_type,
            source=self.source,
            sensitivity=self.sensitivity,
            importance=self.importance,
            confidence=self.confidence,
            tags=self.tags,
            project_id=self.project_id,
        )
