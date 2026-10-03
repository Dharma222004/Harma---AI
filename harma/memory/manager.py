"""
Harma Long-Term Memory — Memory Manager — Phase 5

The central orchestrator for all long-term memory operations.

This is the only public interface the rest of Harma should use.
Other modules (agent, tools, context) import MemoryManager — not store/retrieval directly.

Responsibilities:
  1. Remember:      validate → privacy check → persist
  2. Recall/Search: retrieve → rank → format for context
  3. Update:        find existing → supersede or update in-place
  4. Forget:        soft-delete by ID or query match
  5. Extract:       analyse user utterance for candidate memories
  6. Context Build: format top-K memories for LLM system context

Failure policy:
  Memory errors MUST NOT crash the agent.
  All public methods return results or log errors silently.
  The agent continues operating even if the memory store is unavailable.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from harma.config.logging_config import get_logger
from harma.config.settings import config
from harma.memory.exceptions import (
    MemoryError, MemoryNotFoundError, MemoryPrivacyError, MemoryStoreError,
)
from harma.memory.extraction import MemoryExtractor
from harma.memory.models import (
    Memory, MemoryCandidate, MemoryQuery, MemorySearchResult,
    MemorySource, MemoryStatus, MemoryType, MemorySensitivity,
)
from harma.memory.privacy import PrivacyFilter
from harma.memory.retrieval import MemoryRetriever
from harma.memory.store import SQLiteMemoryStore

log = get_logger(__name__)


class MemoryManager:
    """
    Single entry point for all Phase 5 long-term memory operations.

    Thread-safe. Gracefully degrades when the store is unavailable.
    """

    def __init__(
        self,
        store: Optional[SQLiteMemoryStore] = None,
        retriever: Optional[MemoryRetriever] = None,
    ) -> None:
        mcfg = config.memory
        db_path = mcfg.long_term_db_path

        self._enabled = getattr(mcfg, "enable_long_term", True)
        self._auto_extract = getattr(mcfg, "auto_extract", True)

        # Retrieval config
        rcfg = getattr(mcfg, "retrieval", None)
        top_k = getattr(rcfg, "top_k", 8) if rcfg else 8
        max_tokens = getattr(rcfg, "max_context_tokens", 1500) if rcfg else 1500

        self._store = store or SQLiteMemoryStore(db_path=db_path)
        self._retriever = retriever or MemoryRetriever(
            store=self._store, top_k=top_k, max_context_tokens=max_tokens
        )
        self._privacy = PrivacyFilter()
        self._extractor = MemoryExtractor()
        self._available = False

        self._initialize()

    def _initialize(self) -> None:
        """Open storage layer. Silently disables memory if it fails."""
        if not self._enabled:
            log.info("[MEMORY] Long-term memory disabled by configuration.")
            return
        try:
            self._store.initialize()
            self._available = True
            log.info("[MEMORY] Long-term memory ready.")
        except Exception as exc:
            log.error("[MEMORY] Failed to initialize store — memory disabled: %s", exc)
            self._available = False

    @property
    def is_available(self) -> bool:
        return self._available and self._enabled

    # ─────────────────────────────────────────────────────────────────────────
    # 1. REMEMBER
    # ─────────────────────────────────────────────────────────────────────────

    def remember(
        self,
        content: str,
        memory_type: MemoryType = MemoryType.SEMANTIC,
        source: MemorySource = MemorySource.EXPLICIT_USER,
        importance: float = 0.8,
        confidence: float = 1.0,
        tags: Optional[list[str]] = None,
        project_id: Optional[str] = None,
    ) -> Optional[Memory]:
        """
        Persist a new long-term memory.

        Args:
            content: The fact/preference/event to remember.
            memory_type: Classification of this memory.
            source: Where the memory came from.
            importance: 0.0–1.0 retention/retrieval weight.
            confidence: 0.0–1.0 reliability of this memory.
            tags: Free-form tags for filtering.
            project_id: Scope to a project.

        Returns:
            The saved Memory, or None if blocked by privacy check or store error.
        """
        if not self.is_available:
            log.warning("[MEMORY] Store unavailable — cannot remember: %r", content[:60])
            return None

        memory = Memory(
            content=content,
            summary=content[:80],
            memory_type=memory_type,
            source=source,
            importance=importance,
            confidence=confidence,
            tags=tags or [],
            project_id=project_id,
        )

        # Privacy check
        result = self._privacy.check(memory)
        if not result.allowed:
            raise MemoryPrivacyError(result.reason)

        try:
            saved = self._store.insert(memory)
            log.info(
                "[MEMORY] Remembered: %r  id=%s  type=%s",
                content[:60], saved.id[:8], memory_type.value,
            )
            return saved
        except Exception as exc:
            log.error("[MEMORY] Failed to persist memory: %s", exc)
            return None

    def remember_candidate(self, candidate: MemoryCandidate) -> Optional[Memory]:
        """Persist a MemoryCandidate produced by the extraction pipeline."""
        return self.remember(
            content=candidate.content,
            memory_type=candidate.memory_type,
            source=candidate.source,
            importance=candidate.importance,
            confidence=candidate.confidence,
            tags=candidate.tags,
            project_id=candidate.project_id,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 2. RECALL / SEARCH
    # ─────────────────────────────────────────────────────────────────────────

    def recall(
        self,
        query: str,
        project_id: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> list[MemorySearchResult]:
        """
        Retrieve memories relevant to a query.

        Returns:
            Ranked list of MemorySearchResult (may be empty if store unavailable).
        """
        if not self.is_available:
            return []
        try:
            return self._retriever.retrieve(
                user_query=query,
                project_id=project_id,
                top_k=top_k,
            )
        except Exception as exc:
            log.warning("[MEMORY] Recall failed: %s", exc)
            return []

    def search(
        self,
        query: str,
        memory_types: Optional[list[MemoryType]] = None,
        project_id: Optional[str] = None,
        top_k: int = 10,
    ) -> list[Memory]:
        """
        Search memories explicitly (for tool use / user-facing operations).

        Returns raw Memory objects, not scored results.
        """
        if not self.is_available:
            return []
        try:
            mq = MemoryQuery(
                text=query,
                memory_types=memory_types or [],
                project_id=project_id,
                top_k=top_k,
            )
            return self._store.search(mq)
        except Exception as exc:
            log.warning("[MEMORY] Search failed: %s", exc)
            return []

    def get(self, memory_id: str) -> Optional[Memory]:
        """Retrieve a specific memory by ID."""
        if not self.is_available:
            return None
        try:
            return self._store.get(memory_id)
        except MemoryNotFoundError:
            return None
        except Exception as exc:
            log.warning("[MEMORY] get(%s) failed: %s", memory_id[:8], exc)
            return None

    def list_memories(
        self,
        limit: int = 50,
        status: MemoryStatus = MemoryStatus.ACTIVE,
    ) -> list[Memory]:
        """List recent active memories."""
        if not self.is_available:
            return []
        try:
            return self._store.list_all(status=status, limit=limit)
        except Exception as exc:
            log.warning("[MEMORY] list_memories failed: %s", exc)
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # 3. UPDATE
    # ─────────────────────────────────────────────────────────────────────────

    def update(
        self,
        memory_id: str,
        new_content: str,
        source: MemorySource = MemorySource.USER_CORRECTION,
    ) -> Optional[Memory]:
        """
        Update an existing memory with new content.
        Creates a new memory that supersedes the old one (for auditability).
        """
        if not self.is_available:
            return None
        old = self.get(memory_id)
        if old is None:
            raise MemoryNotFoundError(f"Memory '{memory_id}' not found.")

        new_memory = Memory(
            content=new_content,
            summary=new_content[:80],
            memory_type=old.memory_type,
            source=source,
            importance=old.importance,
            confidence=1.0,   # user correction = high confidence
            tags=old.tags,
            project_id=old.project_id,
        )

        # Privacy check on new content
        result = self._privacy.check(new_memory)
        if not result.allowed:
            raise MemoryPrivacyError(result.reason)

        try:
            saved = self._store.supersede(old_id=memory_id, new_memory=new_memory)
            log.info(
                "[MEMORY] Updated memory %s → %s", memory_id[:8], saved.id[:8]
            )
            return saved
        except Exception as exc:
            log.error("[MEMORY] Update failed: %s", exc)
            return None

    def correct(
        self,
        query: str = "",
        new_content: str = "",
        project_id: Optional[str] = None,
        old_query: Optional[str] = None,
    ) -> tuple[int, Optional[Memory]]:
        """
        User correction: find memories matching query, supersede them,
        and store the corrected version.

        Returns: (num_superseded, new_memory)
        """
        if not self.is_available:
            return 0, None

        search_query = (old_query or query).strip()
        # Find matching active memories
        matches = self.search(query=search_query, project_id=project_id, top_k=5)
        active_matches = [m for m in matches if m.is_active()]

        if not active_matches:
            # No existing memory to correct — just create a new one
            new = self.remember(
                content=new_content,
                source=MemorySource.USER_CORRECTION,
                project_id=project_id,
                importance=0.9,
                confidence=1.0,
            )
            return 0, new

        # Supersede all matching memories with the correction
        new_memory = None
        for i, old in enumerate(active_matches):
            if i == 0:
                # First one: create correction and supersede
                try:
                    new_mem = Memory(
                        content=new_content,
                        summary=new_content[:80],
                        memory_type=old.memory_type,
                        source=MemorySource.USER_CORRECTION,
                        importance=old.importance,
                        confidence=1.0,
                        tags=old.tags,
                        project_id=old.project_id,
                    )
                    result = self._privacy.check(new_mem)
                    if result.allowed:
                        new_memory = self._store.supersede(old.id, new_mem)
                except Exception as exc:
                    log.error("[MEMORY] Correction supersede failed: %s", exc)
            else:
                # Subsequent matches: just soft-delete
                try:
                    self._store.soft_delete(old.id)
                except Exception:
                    pass

        return len(active_matches), new_memory

    # ─────────────────────────────────────────────────────────────────────────
    # 4. FORGET
    # ─────────────────────────────────────────────────────────────────────────

    def forget(self, memory_id: str) -> bool:
        """Soft-delete a memory by ID. Returns True if deleted."""
        if not self.is_available:
            return False
        try:
            self._store.soft_delete(memory_id)
            log.info("[MEMORY] Forgotten memory %s", memory_id[:8])
            return True
        except MemoryNotFoundError:
            return False
        except Exception as exc:
            log.error("[MEMORY] Forget failed: %s", exc)
            return False

    def forget_matching(
        self,
        query: str,
        project_id: Optional[str] = None,
    ) -> int:
        """Soft-delete all active memories matching query. Returns count."""
        if not self.is_available:
            return 0
        matches = self.search(query=query, project_id=project_id, top_k=50)
        active = [m.id for m in matches if m.is_active()]
        if not active:
            return 0
        try:
            return self._store.soft_delete_many(active)
        except Exception as exc:
            log.error("[MEMORY] Bulk forget failed: %s", exc)
            return 0

    def forget_project(self, project_id: str) -> int:
        """Soft-delete all memories scoped to a project. Returns count."""
        if not self.is_available:
            return 0
        try:
            mq = MemoryQuery(
                project_id=project_id,
                status_filter=[MemoryStatus.ACTIVE],
                top_k=500,
            )
            matches = self._store.search(mq)
            ids = [m.id for m in matches]
            if not ids:
                return 0
            return self._store.soft_delete_many(ids)
        except Exception as exc:
            log.error("[MEMORY] Forget project failed: %s", exc)
            return 0

    def forget_all(self) -> int:
        """Soft-delete ALL active memories. Returns count. Requires explicit call."""
        if not self.is_available:
            return 0
        try:
            mq = MemoryQuery(status_filter=[MemoryStatus.ACTIVE], top_k=10000)
            all_active = self._store.search(mq)
            ids = [m.id for m in all_active]
            if not ids:
                return 0
            return self._store.soft_delete_many(ids)
        except Exception as exc:
            log.error("[MEMORY] Forget-all failed: %s", exc)
            return 0

    # ─────────────────────────────────────────────────────────────────────────
    # 5. EXTRACTION
    # ─────────────────────────────────────────────────────────────────────────

    def extract_and_save(
        self,
        user_text: str,
        project_id: Optional[str] = None,
        auto_save: Optional[bool] = None,
    ) -> list[Memory]:
        """
        Extract candidate memories from user text and optionally persist them.

        Args:
            user_text: The user's utterance.
            project_id: Active project context.
            auto_save: If None, use config.memory.auto_extract.

        Returns:
            List of persisted Memory objects (may be empty).
        """
        if not self.is_available:
            return []

        should_save = auto_save if auto_save is not None else self._auto_extract

        try:
            candidates = self._extractor.extract(user_text, project_id=project_id)
        except Exception as exc:
            log.warning("[MEMORY] Extraction failed: %s", exc)
            return []

        if not candidates:
            return []

        if not should_save:
            log.info("[MEMORY] Extracted %d candidates (not auto-saved).", len(candidates))
            return []

        saved: list[Memory] = []
        for candidate in candidates:
            try:
                mem = self.remember_candidate(candidate)
                if mem:
                    saved.append(mem)
            except MemoryPrivacyError as exc:
                log.info("[MEMORY] Candidate blocked by privacy: %s", exc)
            except Exception as exc:
                log.warning("[MEMORY] Could not save candidate: %s", exc)

        return saved

    # ─────────────────────────────────────────────────────────────────────────
    # 6. CONTEXT BUILDING
    # ─────────────────────────────────────────────────────────────────────────

    def build_context(
        self,
        user_query: str,
        project_id: Optional[str] = None,
    ) -> str:
        """
        Retrieve and format relevant memories for injection into LLM context.

        Returns an empty string if no relevant memories exist or store is unavailable.
        Memory is marked as DATA — never as instructions.
        """
        if not self.is_available:
            return ""
        try:
            results = self.recall(user_query, project_id=project_id)
            if not results:
                return ""
            return self._retriever.format_for_context(results, user_query)
        except Exception as exc:
            log.warning("[MEMORY] Context build failed: %s", exc)
            return ""

    # ─────────────────────────────────────────────────────────────────────────
    # 7. STATS
    # ─────────────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return summary statistics about the memory store."""
        if not self.is_available:
            return {"available": False}
        try:
            s = self._store.stats()
            s["available"] = True
            return s
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    def summary(self) -> str:
        """Human-readable memory summary."""
        s = self.stats()
        if not s.get("available"):
            return "Long-term memory: unavailable"
        return (
            f"Long-term memory: {s.get('active', 0)} active memories  "
            f"({s.get('total', 0)} total)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton (lazy-initialized)
# ─────────────────────────────────────────────────────────────────────────────

_memory_manager: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    """Return the shared MemoryManager singleton (initialise on first call)."""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager


def reset_memory_manager() -> None:
    """Reset the singleton (used in tests)."""
    global _memory_manager
    _memory_manager = None
