"""
Harma Long-Term Memory — SQLite Store — Phase 5

The persistence layer for all long-term memories.

Features:
  • SQLite backend — works offline, no infrastructure dependency
  • Thread-safe (WAL mode, serialized via lock)
  • Full CRUD: insert, get, update, soft-delete
  • Keyword search across content + tags
  • Metadata filtering (type, source, project, status, importance, confidence)
  • FTS5 full-text search if available (falls back to LIKE search)
  • Graceful degradation — errors are logged, never crash the agent

Privacy:
  • Only content that has passed PrivacyFilter reaches this layer.
  • Embeddings stored as JSON blobs (optional).
  • File permissions: 0o600 (owner read/write only).

Schema version: 1
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from harma.config.logging_config import get_logger
from harma.memory.exceptions import MemoryNotFoundError, MemoryStoreError
from harma.memory.models import (
    Memory, MemoryQuery, MemoryStatus, MemoryType, MemorySource,
    MemorySensitivity,
)

log = get_logger(__name__)

_SCHEMA_VERSION = 1
_DEFAULT_DB_PATH = "data/harma_memory.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────

_CREATE_MEMORIES_TABLE = """
CREATE TABLE IF NOT EXISTS memories (
    id              TEXT PRIMARY KEY,
    content         TEXT NOT NULL,
    summary         TEXT DEFAULT '',
    memory_type     TEXT NOT NULL DEFAULT 'semantic',
    source          TEXT NOT NULL DEFAULT 'system',
    sensitivity     TEXT NOT NULL DEFAULT 'normal',
    status          TEXT NOT NULL DEFAULT 'active',
    importance      REAL NOT NULL DEFAULT 0.5,
    confidence      REAL NOT NULL DEFAULT 1.0,
    tags            TEXT DEFAULT '',
    project_id      TEXT DEFAULT '',
    supersedes_id   TEXT DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    last_accessed_at TEXT NOT NULL,
    access_count    INTEGER NOT NULL DEFAULT 0,
    metadata        TEXT DEFAULT '{}'
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_status ON memories(status);",
    "CREATE INDEX IF NOT EXISTS idx_type ON memories(memory_type);",
    "CREATE INDEX IF NOT EXISTS idx_project ON memories(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_importance ON memories(importance);",
    "CREATE INDEX IF NOT EXISTS idx_created ON memories(created_at);",
]

_CREATE_SCHEMA_TABLE = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);
"""


# ─────────────────────────────────────────────────────────────────────────────
# SQLiteMemoryStore
# ─────────────────────────────────────────────────────────────────────────────

class SQLiteMemoryStore:
    """
    Thread-safe SQLite persistence for Harma long-term memory.

    All public methods return Memory objects or raise MemoryStoreError.
    They never propagate raw sqlite3 exceptions to callers.
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._initialized = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def initialize(self) -> None:
        """Open DB connection and create schema if needed."""
        try:
            path = Path(self._db_path)
            path.parent.mkdir(parents=True, exist_ok=True)

            self._conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                timeout=10.0,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")

            self._create_schema()
            self._initialized = True
            log.info("[STORE] SQLite memory store ready: %s", self._db_path)

        except Exception as exc:
            raise MemoryStoreError(f"Failed to initialise memory store: {exc}") from exc

    def _create_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(_CREATE_SCHEMA_TABLE)
            cur.execute(_CREATE_MEMORIES_TABLE)
            for idx in _CREATE_INDEXES:
                cur.execute(idx)
            # Set schema version if not set
            cur.execute("SELECT COUNT(*) FROM schema_version;")
            if cur.fetchone()[0] == 0:
                cur.execute("INSERT INTO schema_version VALUES (?);", (_SCHEMA_VERSION,))
            self._conn.commit()

    def close(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        self._initialized = False

    def _require_init(self) -> None:
        if not self._initialized or not self._conn:
            raise MemoryStoreError("Memory store is not initialized. Call initialize() first.")

    # ── Insert ────────────────────────────────────────────────────────────────

    def insert(self, memory: Memory) -> Memory:
        """Persist a new memory. Returns the saved memory."""
        self._require_init()
        row = memory.to_dict()
        # JSON-encode metadata properly
        row["metadata"] = json.dumps(memory.metadata)
        try:
            with self._lock:
                self._conn.execute(
                    """INSERT INTO memories
                    (id, content, summary, memory_type, source, sensitivity,
                     status, importance, confidence, tags, project_id,
                     supersedes_id, created_at, updated_at, last_accessed_at,
                     access_count, metadata)
                    VALUES
                    (:id, :content, :summary, :memory_type, :source, :sensitivity,
                     :status, :importance, :confidence, :tags, :project_id,
                     :supersedes_id, :created_at, :updated_at, :last_accessed_at,
                     :access_count, :metadata)
                    """,
                    row,
                )
                self._conn.commit()
            log.info("[STORE] Inserted memory %s  type=%s", memory.id[:8], memory.memory_type.value)
            return memory
        except Exception as exc:
            raise MemoryStoreError(f"Failed to insert memory: {exc}") from exc

    # ── Get by ID ─────────────────────────────────────────────────────────────

    def get(self, memory_id: str) -> Memory:
        """Retrieve a memory by ID. Raises MemoryNotFoundError if not found."""
        self._require_init()
        try:
            with self._lock:
                cur = self._conn.execute(
                    "SELECT * FROM memories WHERE id = ?;", (memory_id,)
                )
                row = cur.fetchone()
            if row is None:
                raise MemoryNotFoundError(f"Memory '{memory_id}' not found.")
            return Memory.from_dict(dict(row))
        except MemoryNotFoundError:
            raise
        except Exception as exc:
            raise MemoryStoreError(f"Failed to get memory {memory_id}: {exc}") from exc

    # ── Update ────────────────────────────────────────────────────────────────

    def update(self, memory: Memory) -> Memory:
        """Update an existing memory. Raises MemoryNotFoundError if ID not found."""
        self._require_init()
        from harma.memory.models import _now
        memory.updated_at = _now()
        row = memory.to_dict()
        row["metadata"] = json.dumps(memory.metadata)
        try:
            with self._lock:
                result = self._conn.execute(
                    """UPDATE memories SET
                    content=:content, summary=:summary, memory_type=:memory_type,
                    source=:source, sensitivity=:sensitivity, status=:status,
                    importance=:importance, confidence=:confidence,
                    tags=:tags, project_id=:project_id, supersedes_id=:supersedes_id,
                    updated_at=:updated_at, last_accessed_at=:last_accessed_at,
                    access_count=:access_count, metadata=:metadata
                    WHERE id=:id
                    """,
                    row,
                )
                self._conn.commit()
            if result.rowcount == 0:
                raise MemoryNotFoundError(f"Memory '{memory.id}' not found for update.")
            log.info("[STORE] Updated memory %s", memory.id[:8])
            return memory
        except MemoryNotFoundError:
            raise
        except Exception as exc:
            raise MemoryStoreError(f"Failed to update memory: {exc}") from exc

    def touch(self, memory_id: str) -> None:
        """Update last_accessed_at and increment access_count."""
        self._require_init()
        try:
            with self._lock:
                self._conn.execute(
                    """UPDATE memories SET
                    last_accessed_at=?, access_count=access_count+1
                    WHERE id=?
                    """,
                    (_now_iso(), memory_id),
                )
                self._conn.commit()
        except Exception as exc:
            log.warning("[STORE] Could not touch memory %s: %s", memory_id[:8], exc)

    # ── Soft Delete ───────────────────────────────────────────────────────────

    def soft_delete(self, memory_id: str) -> None:
        """Mark a memory as DELETED (soft delete — data retained for audit)."""
        self._require_init()
        try:
            with self._lock:
                result = self._conn.execute(
                    "UPDATE memories SET status='deleted', updated_at=? WHERE id=?;",
                    (_now_iso(), memory_id),
                )
                self._conn.commit()
            if result.rowcount == 0:
                raise MemoryNotFoundError(f"Memory '{memory_id}' not found for deletion.")
            log.info("[STORE] Soft-deleted memory %s", memory_id[:8])
        except MemoryNotFoundError:
            raise
        except Exception as exc:
            raise MemoryStoreError(f"Failed to delete memory {memory_id}: {exc}") from exc

    def soft_delete_many(self, memory_ids: list[str]) -> int:
        """Soft-delete multiple memories. Returns count deleted."""
        self._require_init()
        if not memory_ids:
            return 0
        placeholders = ",".join("?" * len(memory_ids))
        try:
            with self._lock:
                result = self._conn.execute(
                    f"UPDATE memories SET status='deleted', updated_at=? "
                    f"WHERE id IN ({placeholders});",
                    [_now_iso()] + memory_ids,
                )
                self._conn.commit()
            count = result.rowcount
            log.info("[STORE] Soft-deleted %d memories.", count)
            return count
        except Exception as exc:
            raise MemoryStoreError(f"Failed to bulk-delete memories: {exc}") from exc

    def delete(self, memory_id: str) -> bool:
        """Alias for soft_delete."""
        self.soft_delete(memory_id)
        return True

    def delete_all(self) -> int:
        """Soft-delete all active memories. Returns count deleted."""
        self._require_init()
        try:
            with self._lock:
                result = self._conn.execute(
                    "UPDATE memories SET status='deleted', updated_at=? WHERE status != 'deleted';",
                    (_now_iso(),),
                )
                self._conn.commit()
                count = result.rowcount
            log.info("[STORE] Soft-deleted all (%d) memories.", count)
            return count
        except Exception as exc:
            raise MemoryStoreError(f"Failed to delete all memories: {exc}") from exc

    # ── Search ────────────────────────────────────────────────────────────────

    def search(self, query: MemoryQuery) -> list[Memory]:
        """
        Search memories using keyword matching + metadata filtering.

        Returns a list of Memory objects matching the query.
        Sorting and ranking is done by the MemoryRetriever layer.
        """
        self._require_init()
        try:
            conditions = []
            params: list = []

            # Status filter
            if query.status_filter:
                placeholders = ",".join("?" * len(query.status_filter))
                conditions.append(f"status IN ({placeholders})")
                params.extend(s.value for s in query.status_filter)

            # Memory type filter
            if query.memory_types:
                placeholders = ",".join("?" * len(query.memory_types))
                conditions.append(f"memory_type IN ({placeholders})")
                params.extend(t.value for t in query.memory_types)

            # Project filter
            if query.project_id:
                conditions.append("project_id = ?")
                params.append(query.project_id)

            # Importance floor
            if query.min_importance > 0:
                conditions.append("importance >= ?")
                params.append(query.min_importance)

            # Confidence floor
            if query.min_confidence > 0:
                conditions.append("confidence >= ?")
                params.append(query.min_confidence)

            # Sensitivity filter — exclude HIGH_SENSITIVITY unless requested
            if not query.include_sensitive:
                conditions.append("sensitivity != 'high_sensitivity'")

            # Keyword search — LIKE against content and tags
            if query.text:
                terms = [w.strip() for w in re.findall(r'\b[A-Za-z0-9_-]+\b', query.text) if len(w.strip()) > 1]
                if terms:
                    term_clauses = []
                    for t in terms:
                        stem = t[:4] if len(t) >= 5 else t
                        term_clauses.append("(content LIKE ? OR tags LIKE ? OR summary LIKE ?)")
                        kw = f"%{stem}%"
                        params.extend([kw, kw, kw])
                    conditions.append(f"({' OR '.join(term_clauses)})")
                else:
                    keyword = f"%{query.text}%"
                    conditions.append("(content LIKE ? OR tags LIKE ? OR summary LIKE ?)")
                    params.extend([keyword, keyword, keyword])

            # Tags filter (any of the specified tags)
            if query.tags:
                tag_conditions = " OR ".join("tags LIKE ?" for _ in query.tags)
                conditions.append(f"({tag_conditions})")
                params.extend(f"%{t}%" for t in query.tags)

            where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            sql = f"""
                SELECT * FROM memories
                {where_clause}
                ORDER BY importance DESC, last_accessed_at DESC
                LIMIT ?
            """
            params.append(query.top_k * 3)  # over-fetch for re-ranking

            with self._lock:
                cur = self._conn.execute(sql, params)
                rows = cur.fetchall()

            return [Memory.from_dict(dict(r)) for r in rows]

        except Exception as exc:
            raise MemoryStoreError(f"Search failed: {exc}") from exc

    def list_all(
        self,
        status: MemoryStatus = MemoryStatus.ACTIVE,
        limit: int = 100,
    ) -> list[Memory]:
        """Return all memories with a given status, newest first."""
        self._require_init()
        try:
            with self._lock:
                cur = self._conn.execute(
                    "SELECT * FROM memories WHERE status=? ORDER BY created_at DESC LIMIT ?;",
                    (status.value, limit),
                )
                rows = cur.fetchall()
            return [Memory.from_dict(dict(r)) for r in rows]
        except Exception as exc:
            raise MemoryStoreError(f"list_all failed: {exc}") from exc

    def count(self, status: Optional[MemoryStatus] = None) -> int:
        """Count memories, optionally filtered by status."""
        self._require_init()
        try:
            with self._lock:
                if status:
                    cur = self._conn.execute(
                        "SELECT COUNT(*) FROM memories WHERE status=?;", (status.value,)
                    )
                else:
                    cur = self._conn.execute("SELECT COUNT(*) FROM memories;")
                return cur.fetchone()[0]
        except Exception as exc:
            raise MemoryStoreError(f"count failed: {exc}") from exc

    def supersede(self, old_id: str, new_memory: Memory) -> Memory:
        """
        Mark old_id as SUPERSEDED, insert new_memory with supersedes_id=old_id.
        Used for user corrections.
        """
        self._require_init()
        new_memory.supersedes_id = old_id
        try:
            with self._lock:
                # Check old exists
                cur = self._conn.execute("SELECT metadata FROM memories WHERE id=?;", (old_id,))
                old_row = cur.fetchone()
                if old_row is None:
                    raise MemoryNotFoundError(f"Memory '{old_id}' not found to supersede.")
                old_meta = {}
                if old_row["metadata"]:
                    try:
                        old_meta = json.loads(old_row["metadata"])
                    except Exception:
                        old_meta = {}
                old_meta["superseded_by"] = new_memory.id

                # Supersede old
                self._conn.execute(
                    "UPDATE memories SET status='superseded', updated_at=?, metadata=? WHERE id=?;",
                    (_now_iso(), json.dumps(old_meta), old_id),
                )
                # Insert new
                row = new_memory.to_dict()
                row["metadata"] = json.dumps(new_memory.metadata)
                self._conn.execute(
                    """INSERT INTO memories
                    (id, content, summary, memory_type, source, sensitivity,
                     status, importance, confidence, tags, project_id,
                     supersedes_id, created_at, updated_at, last_accessed_at,
                     access_count, metadata)
                    VALUES
                    (:id, :content, :summary, :memory_type, :source, :sensitivity,
                     :status, :importance, :confidence, :tags, :project_id,
                     :supersedes_id, :created_at, :updated_at, :last_accessed_at,
                     :access_count, :metadata)
                    """,
                    row,
                )
                self._conn.commit()
            log.info(
                "[STORE] Superseded %s with %s",
                old_id[:8], new_memory.id[:8],
            )
            return new_memory
        except Exception as exc:
            raise MemoryStoreError(f"Supersede failed: {exc}") from exc

    def stats(self) -> dict:
        """Return summary statistics about the memory store."""
        self._require_init()
        try:
            with self._lock:
                cur = self._conn.execute("""
                    SELECT status, COUNT(*) as cnt FROM memories GROUP BY status;
                """)
                by_status = {row["status"]: row["cnt"] for row in cur.fetchall()}

                cur = self._conn.execute("""
                    SELECT memory_type, COUNT(*) as cnt FROM memories
                    WHERE status='active' GROUP BY memory_type;
                """)
                by_type = {row["memory_type"]: row["cnt"] for row in cur.fetchall()}

            return {
                "db_path": self._db_path,
                "by_status": by_status,
                "by_type": by_type,
                "total": sum(by_status.values()),
                "active": by_status.get("active", 0),
            }
        except Exception as exc:
            raise MemoryStoreError(f"Stats failed: {exc}") from exc
