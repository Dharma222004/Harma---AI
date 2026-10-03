"""
Harma Runtime V3 — Experience Memory Store (spec §35, §36)

Extends Harma's existing SQLite memory database with indexed experience tables:

    v3_procedures   procedural memory      (indexed: task_pattern, status, confidence, last_used_at)
    v3_templates    request templates → procedure
    v3_episodes     episodic memory        (indexed: task_type, procedure_id, outcome, created_at)
    v3_failures     failure memory         (indexed: task_pattern, procedure_id, failure_type)
    v3_corrections  correction memory      (indexed: kind, active)
    v3_semantic     semantic knowledge     (PK: category, key)

Template matching runs against an in-process cache, so trivial commands never pay for
an expensive search.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from harma.config.logging_config import get_logger
from harma.core.v3.experience import templates as tpl
from harma.core.v3.experience.models import (
    Correction, Episode, FailureExperience, Procedure, ProcedureStatus, SemanticFact,
)

log = get_logger(__name__)

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS v3_procedures (
        procedure_id TEXT PRIMARY KEY, proc_key TEXT NOT NULL, task_pattern TEXT NOT NULL,
        status TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 0, success_count INTEGER DEFAULT 0,
        failure_count INTEGER DEFAULT 0, risk_level TEXT DEFAULT 'low', capabilities TEXT DEFAULT '',
        last_used_at REAL DEFAULT 0, last_success_at REAL DEFAULT 0, updated_at REAL DEFAULT 0,
        data TEXT NOT NULL)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_v3p_key ON v3_procedures(proc_key)",
    "CREATE INDEX IF NOT EXISTS idx_v3p_pattern ON v3_procedures(task_pattern)",
    "CREATE INDEX IF NOT EXISTS idx_v3p_status ON v3_procedures(status, confidence)",
    "CREATE INDEX IF NOT EXISTS idx_v3p_used ON v3_procedures(last_used_at)",
    """CREATE TABLE IF NOT EXISTS v3_templates (
        template TEXT NOT NULL, procedure_id TEXT NOT NULL, created_at REAL DEFAULT 0,
        PRIMARY KEY (template, procedure_id))""",
    "CREATE INDEX IF NOT EXISTS idx_v3t_proc ON v3_templates(procedure_id)",
    """CREATE TABLE IF NOT EXISTS v3_episodes (
        episode_id TEXT PRIMARY KEY, run_id TEXT, task_type TEXT, strategy TEXT, template TEXT,
        procedure_id TEXT, outcome TEXT, duration_ms REAL, llm_calls INTEGER, created_at REAL,
        data TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_v3e_type ON v3_episodes(task_type, outcome)",
    "CREATE INDEX IF NOT EXISTS idx_v3e_proc ON v3_episodes(procedure_id)",
    "CREATE INDEX IF NOT EXISTS idx_v3e_created ON v3_episodes(created_at)",
    """CREATE TABLE IF NOT EXISTS v3_failures (
        failure_id TEXT PRIMARY KEY, task_pattern TEXT, procedure_id TEXT, template TEXT,
        failure_type TEXT, occurrences INTEGER DEFAULT 1, confidence REAL, updated_at REAL,
        data TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_v3f_pattern ON v3_failures(task_pattern, failure_type)",
    "CREATE INDEX IF NOT EXISTS idx_v3f_proc ON v3_failures(procedure_id)",
    """CREATE TABLE IF NOT EXISTS v3_corrections (
        correction_id TEXT PRIMARY KEY, kind TEXT, subject TEXT, replaces TEXT, active INTEGER,
        created_at REAL, data TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_v3c_kind ON v3_corrections(kind, active)",
    """CREATE TABLE IF NOT EXISTS v3_semantic (
        category TEXT NOT NULL, key TEXT NOT NULL, value TEXT, confidence REAL, source TEXT,
        updated_at REAL, PRIMARY KEY (category, key))""",
]


class ExperienceStore:
    """Thread-safe SQLite experience memory. Never raises into the agent loop."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        if self.db_path != ":memory:":
            try:
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                import tempfile
                self.db_path = str(Path(tempfile.gettempdir()) / Path(self.db_path).name)
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10.0)
        except (sqlite3.OperationalError, OSError):
            self.db_path = ":memory:"
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10.0)
        self._conn.row_factory = sqlite3.Row
        if self.db_path != ":memory:":
            try:
                self._conn.execute("PRAGMA journal_mode=WAL;")
            except Exception:
                pass
        with self._lock:
            for stmt in _SCHEMA:
                self._conn.execute(stmt)
            self._conn.commit()
        self._template_cache: dict[str, list[str]] = {}   # template -> [procedure_id]
        self._reload_template_cache()

    # ── Internals ─────────────────────────────────────────────────────────────

    def _exec(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def _rows(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def _reload_template_cache(self) -> None:
        cache: dict[str, list[str]] = {}
        for r in self._rows("SELECT template, procedure_id FROM v3_templates"):
            cache.setdefault(r["template"], []).append(r["procedure_id"])
        self._template_cache = cache

    # ── Procedures ────────────────────────────────────────────────────────────

    def upsert_procedure(self, proc: Procedure, proc_key: str) -> Procedure:
        self._exec(
            """INSERT INTO v3_procedures (procedure_id, proc_key, task_pattern, status, confidence,
                   success_count, failure_count, risk_level, capabilities, last_used_at, last_success_at,
                   updated_at, data)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(procedure_id) DO UPDATE SET status=excluded.status, confidence=excluded.confidence,
                   success_count=excluded.success_count, failure_count=excluded.failure_count,
                   risk_level=excluded.risk_level, capabilities=excluded.capabilities,
                   last_used_at=excluded.last_used_at, last_success_at=excluded.last_success_at,
                   updated_at=excluded.updated_at, data=excluded.data""",
            (proc.procedure_id, proc_key, proc.task_pattern, proc.status.value, proc.confidence,
             proc.success_count, proc.failure_count, proc.risk_level, ",".join(proc.capabilities),
             proc.last_used_at, proc.last_success_at, time.time(), json.dumps(proc.to_dict(), default=str)),
        )
        for t in proc.templates:
            self.add_template(proc.procedure_id, t)
        return proc

    def add_template(self, procedure_id: str, template: str) -> None:
        self._exec("INSERT OR IGNORE INTO v3_templates (template, procedure_id, created_at) VALUES (?,?,?)",
                   (template, procedure_id, time.time()))
        ids = self._template_cache.setdefault(template, [])
        if procedure_id not in ids:
            ids.append(procedure_id)

    def get_procedure(self, procedure_id: str) -> Optional[Procedure]:
        rows = self._rows("SELECT data FROM v3_procedures WHERE procedure_id=?", (procedure_id,))
        return Procedure.from_dict(json.loads(rows[0]["data"])) if rows else None

    def get_procedure_by_key(self, proc_key: str) -> Optional[Procedure]:
        rows = self._rows("SELECT data FROM v3_procedures WHERE proc_key=?", (proc_key,))
        return Procedure.from_dict(json.loads(rows[0]["data"])) if rows else None

    def list_procedures(self, status: Optional[ProcedureStatus] = None, limit: int = 200) -> list[Procedure]:
        if status:
            rows = self._rows("SELECT data FROM v3_procedures WHERE status=? ORDER BY confidence DESC LIMIT ?",
                              (status.value, limit))
        else:
            rows = self._rows("SELECT data FROM v3_procedures ORDER BY confidence DESC LIMIT ?", (limit,))
        return [Procedure.from_dict(json.loads(r["data"])) for r in rows]

    def find_template_matches(self, request: str) -> list[tuple[Procedure, dict[str, str], str]]:
        """Exact structural matches: the request is an instance of a learned template."""
        out: list[tuple[Procedure, dict[str, str], str]] = []
        for template, proc_ids in list(self._template_cache.items()):
            binds = tpl.match_template(template, request)
            if binds is None:
                continue
            for pid in proc_ids:
                proc = self.get_procedure(pid)
                if proc:
                    out.append((proc, binds, template))
        return out

    def find_similar(self, request: str, limit: int = 3, min_similarity: float = 0.25) -> list[tuple[Procedure, float, str]]:
        scored: list[tuple[float, str, str]] = []
        for template, proc_ids in list(self._template_cache.items()):
            sim = tpl.similarity(request, template)
            if sim >= min_similarity:
                for pid in proc_ids:
                    scored.append((sim, pid, template))
        scored.sort(key=lambda x: -x[0])
        out: list[tuple[Procedure, float, str]] = []
        seen: set[str] = set()
        for sim, pid, template in scored:
            if pid in seen:
                continue
            proc = self.get_procedure(pid)
            if proc and proc.status != ProcedureStatus.DISABLED:
                out.append((proc, round(sim, 3), template))
                seen.add(pid)
            if len(out) >= limit:
                break
        return out

    # ── Episodes ──────────────────────────────────────────────────────────────

    def add_episode(self, ep: Episode) -> None:
        self._exec(
            """INSERT OR REPLACE INTO v3_episodes (episode_id, run_id, task_type, strategy, template,
                   procedure_id, outcome, duration_ms, llm_calls, created_at, data)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (ep.episode_id, ep.run_id, ep.task_type, ep.strategy, ep.template, ep.procedure_id, ep.outcome,
             ep.duration_ms, ep.llm_calls, ep.created_at, json.dumps(ep.to_dict(), default=str)),
        )

    def recent_episodes(self, limit: int = 50, procedure_id: str = "", since: float = 0.0) -> list[dict[str, Any]]:
        if procedure_id:
            rows = self._rows("SELECT data FROM v3_episodes WHERE procedure_id=? AND created_at>=? "
                              "ORDER BY created_at DESC LIMIT ?", (procedure_id, since, limit))
        else:
            rows = self._rows("SELECT data FROM v3_episodes WHERE created_at>=? ORDER BY created_at DESC LIMIT ?",
                              (since, limit))
        return [json.loads(r["data"]) for r in rows]

    # ── Failures ──────────────────────────────────────────────────────────────

    def record_failure(self, f: FailureExperience) -> FailureExperience:
        rows = self._rows(
            "SELECT data FROM v3_failures WHERE task_pattern=? AND failure_type=? AND procedure_id=? AND template=?",
            (f.task_pattern, f.failure_type, f.procedure_id, f.template),
        )
        if rows:
            existing = FailureExperience(**json.loads(rows[0]["data"]))
            existing.occurrences += 1
            existing.reason = f.reason or existing.reason
            existing.better_strategy = f.better_strategy or existing.better_strategy
            existing.observed_state = f.observed_state or existing.observed_state
            existing.confidence = round(min(0.95, existing.confidence + 0.1), 3)
            existing.updated_at = time.time()
            f = existing
        self._exec(
            """INSERT OR REPLACE INTO v3_failures (failure_id, task_pattern, procedure_id, template, failure_type,
                   occurrences, confidence, updated_at, data) VALUES (?,?,?,?,?,?,?,?,?)""",
            (f.failure_id, f.task_pattern, f.procedure_id, f.template, f.failure_type, f.occurrences,
             f.confidence, f.updated_at, json.dumps(f.to_dict(), default=str)),
        )
        return f

    def failures_for(self, task_pattern: str = "", procedure_id: str = "", template: str = "",
                     limit: int = 5) -> list[FailureExperience]:
        clauses, params = [], []
        if procedure_id:
            clauses.append("procedure_id=?"); params.append(procedure_id)
        if template:
            clauses.append("template=?"); params.append(template)
        if task_pattern:
            clauses.append("task_pattern=?"); params.append(task_pattern)
        where = " OR ".join(clauses) if clauses else "1=1"
        rows = self._rows(f"SELECT data FROM v3_failures WHERE {where} ORDER BY updated_at DESC LIMIT ?",
                          (*params, limit))
        return [FailureExperience(**json.loads(r["data"])) for r in rows]

    # ── Corrections ───────────────────────────────────────────────────────────

    def add_correction(self, c: Correction) -> Correction:
        # A newer explicit correction supersedes contradicting older ones.
        if c.kind in ("prefer", "avoid") and c.subject:
            for old in self.active_corrections():
                contradicts = (
                    (old.kind == "prefer" and c.kind == "avoid" and old.subject == c.subject)
                    or (old.kind == "avoid" and c.kind == "prefer" and old.subject == c.subject)
                    or (old.kind == "prefer" and c.kind == "prefer" and old.subject == c.replaces)
                )
                if contradicts:
                    self.deactivate_correction(old.correction_id)
        self._exec(
            "INSERT OR REPLACE INTO v3_corrections (correction_id, kind, subject, replaces, active, created_at, data) "
            "VALUES (?,?,?,?,?,?,?)",
            (c.correction_id, c.kind, c.subject, c.replaces, 1 if c.active else 0, c.created_at,
             json.dumps(c.to_dict(), default=str)),
        )
        return c

    def deactivate_correction(self, correction_id: str) -> None:
        rows = self._rows("SELECT data FROM v3_corrections WHERE correction_id=?", (correction_id,))
        if not rows:
            return
        data = json.loads(rows[0]["data"])
        data["active"] = False
        self._exec("UPDATE v3_corrections SET active=0, data=? WHERE correction_id=?",
                   (json.dumps(data, default=str), correction_id))

    def active_corrections(self) -> list[Correction]:
        rows = self._rows("SELECT data FROM v3_corrections WHERE active=1 ORDER BY created_at DESC")
        return [Correction(**json.loads(r["data"])) for r in rows]

    # ── Semantic knowledge ────────────────────────────────────────────────────

    def upsert_fact(self, fact: SemanticFact) -> None:
        self._exec(
            "INSERT INTO v3_semantic (category, key, value, confidence, source, updated_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(category, key) DO UPDATE SET value=excluded.value, "
            "confidence=MIN(0.99, MAX(v3_semantic.confidence, excluded.confidence) + 0.02), "
            "source=excluded.source, updated_at=excluded.updated_at",
            (fact.category, fact.key.lower(), fact.value, fact.confidence, fact.source, time.time()),
        )

    def get_facts(self, category: str) -> list[SemanticFact]:
        rows = self._rows("SELECT * FROM v3_semantic WHERE category=? ORDER BY confidence DESC", (category,))
        return [SemanticFact(category=r["category"], key=r["key"], value=r["value"] or "",
                             confidence=r["confidence"], source=r["source"], updated_at=r["updated_at"])
                for r in rows]

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        def count(sql: str) -> int:
            return int(self._rows(sql)[0][0])
        return {
            "procedures": count("SELECT COUNT(*) FROM v3_procedures"),
            "trusted": count("SELECT COUNT(*) FROM v3_procedures WHERE status='trusted'"),
            "candidates": count("SELECT COUNT(*) FROM v3_procedures WHERE status='candidate'"),
            "disabled": count("SELECT COUNT(*) FROM v3_procedures WHERE status='disabled'"),
            "templates": count("SELECT COUNT(*) FROM v3_templates"),
            "episodes": count("SELECT COUNT(*) FROM v3_episodes"),
            "failures": count("SELECT COUNT(*) FROM v3_failures"),
            "corrections": count("SELECT COUNT(*) FROM v3_corrections WHERE active=1"),
            "semantic_facts": count("SELECT COUNT(*) FROM v3_semantic"),
        }

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass


_STORE: Optional[ExperienceStore] = None


def get_experience_store() -> ExperienceStore:
    """Process-wide experience store living in Harma's existing memory database."""
    global _STORE
    if _STORE is None:
        from harma.config.settings import config
        path = getattr(config.memory, "long_term_db_path", "data/harma_memory.db")
        try:
            _STORE = ExperienceStore(path)
        except Exception as exc:
            log.warning("[V3][EXPERIENCE] Falling back to in-memory store: %s", exc)
            _STORE = ExperienceStore(":memory:")
    return _STORE
