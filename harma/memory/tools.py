"""
Harma Memory Tools — Phase 5

All memory operations are exposed as BaseTool subclasses so the LLM
can invoke them through the existing Tool Registry + Permission system.

Tools:
    memory_remember       — SENSITIVE  (write new fact)
    memory_search         — SAFE       (read-only search)
    memory_recall         — SAFE       (get by ID)
    memory_update         — SENSITIVE  (update/correct existing)
    memory_forget         — SENSITIVE  (delete by ID)
    memory_forget_query   — SENSITIVE  (delete by keyword match)
    memory_list           — SAFE       (list recent memories)
    memory_stats          — SAFE       (store statistics)
    memory_forget_all     — HIGH_RISK  (bulk delete)

Permission mapping:
    SAFE      → auto-allowed (read-only)
    SENSITIVE → confirmation per permission config
    HIGH_RISK → always requires confirmation

ALL tools use the shared MemoryManager.
NONE create a parallel execution path.
"""

from __future__ import annotations

import json
from typing import Any

from harma.config.logging_config import get_logger
from harma.memory.exceptions import MemoryNotFoundError, MemoryPrivacyError
from harma.memory.manager import get_memory_manager
from harma.memory.models import MemorySource, MemoryType
from harma.tools.base import BaseTool, PermissionLevel, ToolResult

log = get_logger(__name__)


def _ok(data: Any, msg: str = "") -> ToolResult:
    return ToolResult(success=True, output=msg or json.dumps(data, default=str), data=data)


def _err(msg: str) -> ToolResult:
    return ToolResult(success=False, output="", error=msg)


# ─────────────────────────────────────────────────────────────────────────────
# memory_remember
# ─────────────────────────────────────────────────────────────────────────────

class MemoryRememberTool(BaseTool):
    """Save a new fact, preference, or context item to long-term memory."""

    name = "memory_remember"
    description = (
        "Save a piece of information to long-term memory. "
        "Use this when the user says 'remember that', 'note that', "
        "or explicitly states a preference, project detail, or fact they want retained. "
        "Do NOT use this for temporary queries or search results."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The exact fact, preference, or context to remember.",
            },
            "memory_type": {
                "type": "string",
                "enum": ["semantic", "preference", "project", "episodic", "workflow"],
                "description": "Classification of this memory.",
            },
            "importance": {
                "type": "number",
                "description": "Importance score 0.0–1.0. Default 0.8 for explicit statements.",
            },
            "project_id": {
                "type": "string",
                "description": "Optional: scope this memory to a specific project.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags for categorisation.",
            },
        },
        "required": ["content"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        content = kwargs.get("content", "").strip()
        if not content:
            return _err("Content cannot be empty.")

        type_str = kwargs.get("memory_type", "semantic")
        try:
            mtype = MemoryType(type_str)
        except ValueError:
            mtype = MemoryType.SEMANTIC

        importance = float(kwargs.get("importance", 0.8))
        importance = max(0.0, min(1.0, importance))
        project_id = kwargs.get("project_id") or None
        tags = kwargs.get("tags", [])

        mgr = get_memory_manager()
        try:
            mem = mgr.remember(
                content=content,
                memory_type=mtype,
                source=MemorySource.EXPLICIT_USER,
                importance=importance,
                project_id=project_id,
                tags=tags,
            )
            if mem is None:
                return _err("Memory could not be saved (store unavailable).")
            result = {
                "success": True,
                "memory_id": mem.id,
                "memory_type": mem.memory_type.value,
                "content": mem.content,
            }
            return _ok(result, f"Remembered: {content}")
        except MemoryPrivacyError as exc:
            return _err(f"Privacy check failed: {exc}")
        except Exception as exc:
            log.error("[TOOL:memory_remember] Error: %s", exc)
            return _err(f"Could not save memory: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# memory_search
# ─────────────────────────────────────────────────────────────────────────────

class MemorySearchTool(BaseTool):
    """Search long-term memory for relevant information."""

    name = "memory_search"
    description = (
        "Search long-term memory for information relevant to a query. "
        "Use when the user asks what Harma remembers, or when you need context "
        "from previous sessions."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query — what to look for in memory.",
            },
            "memory_type": {
                "type": "string",
                "enum": ["semantic", "preference", "project", "episodic", "workflow", "any"],
                "description": "Filter by memory type. Use 'any' for all types.",
            },
            "project_id": {
                "type": "string",
                "description": "Limit search to a specific project.",
            },
            "top_k": {
                "type": "integer",
                "description": "Maximum number of results to return (default 5).",
            },
        },
        "required": ["query"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query", "").strip()
        if not query:
            return _err("Search query cannot be empty.")

        type_str = kwargs.get("memory_type", "any")
        memory_types = []
        if type_str and type_str != "any":
            try:
                memory_types = [MemoryType(type_str)]
            except ValueError:
                pass

        project_id = kwargs.get("project_id") or None
        top_k = int(kwargs.get("top_k", 5))

        mgr = get_memory_manager()
        memories = mgr.search(
            query=query,
            memory_types=memory_types or None,
            project_id=project_id,
            top_k=top_k,
        )

        if not memories:
            return _ok(
                {"results": [], "count": 0},
                f"No memories found matching '{query}'.",
            )

        results = [
            {
                "id": m.id,
                "content": m.content,
                "type": m.memory_type.value,
                "importance": m.importance,
                "confidence": m.confidence,
                "created_at": m.created_at.isoformat(),
            }
            for m in memories
        ]
        summary = "\n".join(f"- [{m.memory_type.value}] {m.content}" for m in memories)
        return _ok(
            {"results": results, "memories": results, "count": len(results)},
            f"Found {len(results)} memories:\n{summary}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# memory_recall (get by ID)
# ─────────────────────────────────────────────────────────────────────────────

class MemoryRecallTool(BaseTool):
    """Retrieve a specific memory by its ID."""

    name = "memory_recall"
    description = "Retrieve a specific memory entry by its unique ID."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": "The unique ID of the memory to retrieve.",
            }
        },
        "required": ["memory_id"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        memory_id = kwargs.get("memory_id", "").strip()
        if not memory_id:
            return _err("memory_id is required.")
        mgr = get_memory_manager()
        mem = mgr.get(memory_id)
        if mem is None:
            return _err(f"Memory '{memory_id}' not found.")
        return _ok(
            {"id": mem.id, "content": mem.content, "type": mem.memory_type.value},
            mem.content,
        )


# ─────────────────────────────────────────────────────────────────────────────
# memory_update
# ─────────────────────────────────────────────────────────────────────────────

class MemoryUpdateTool(BaseTool):
    """Update or correct an existing memory entry."""

    name = "memory_update"
    description = (
        "Update or correct an existing memory. "
        "Use when the user says 'actually, update that to…' or corrects a previous statement. "
        "The old memory is preserved as 'superseded' for audit purposes."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": "ID of the memory to update.",
            },
            "new_content": {
                "type": "string",
                "description": "The corrected/updated content.",
            },
        },
        "required": ["memory_id", "new_content"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        memory_id = kwargs.get("memory_id", "").strip()
        new_content = kwargs.get("new_content", "").strip()
        if not memory_id or not new_content:
            return _err("Both memory_id and new_content are required.")
        mgr = get_memory_manager()
        try:
            updated = mgr.update(
                memory_id=memory_id,
                new_content=new_content,
                source=MemorySource.USER_CORRECTION,
            )
            if updated is None:
                return _err("Update failed — store unavailable.")
            return _ok(
                {"memory_id": updated.id, "new_memory_id": updated.id, "content": updated.content},
                f"Updated memory: {new_content}",
            )
        except MemoryNotFoundError:
            return _err(f"Memory '{memory_id}' not found.")
        except MemoryPrivacyError as exc:
            return _err(f"Privacy check failed: {exc}")
        except Exception as exc:
            log.error("[TOOL:memory_update] Error: %s", exc)
            return _err(f"Update failed: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# memory_forget (by ID)
# ─────────────────────────────────────────────────────────────────────────────

class MemoryForgetTool(BaseTool):
    """Delete a specific memory by ID."""

    name = "memory_forget"
    description = (
        "Delete a specific memory by its ID. "
        "Use when the user says 'forget that' and you have the memory ID, "
        "or when correcting erroneous stored information."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": "The unique ID of the memory to delete.",
            }
        },
        "required": ["memory_id"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        memory_id = kwargs.get("memory_id", "").strip()
        if not memory_id:
            return _err("memory_id is required.")
        mgr = get_memory_manager()
        deleted = mgr.forget(memory_id)
        if deleted:
            return _ok({"deleted": True, "memory_id": memory_id}, "Memory deleted.")
        return _err(f"Memory '{memory_id}' not found.")


# ─────────────────────────────────────────────────────────────────────────────
# memory_forget_query (by keyword match)
# ─────────────────────────────────────────────────────────────────────────────

class MemoryForgetQueryTool(BaseTool):
    """Delete all memories matching a keyword search query."""

    name = "memory_forget_query"
    description = (
        "Delete all memories matching a keyword query. "
        "For example: 'forget everything about Python' or 'delete all Harma project memories'. "
        "Use memory_search first to confirm what will be deleted."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keywords matching memories to delete.",
            },
            "project_id": {
                "type": "string",
                "description": "Limit deletion to a specific project.",
            },
        },
        "required": ["query"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query", "").strip()
        if not query:
            return _err("Query cannot be empty.")
        project_id = kwargs.get("project_id") or None
        mgr = get_memory_manager()
        count = mgr.forget_matching(query=query, project_id=project_id)
        return _ok(
            {"deleted_count": count},
            f"Deleted {count} memories matching '{query}'.",
        )


# ─────────────────────────────────────────────────────────────────────────────
# memory_list
# ─────────────────────────────────────────────────────────────────────────────

class MemoryListTool(BaseTool):
    """List recent long-term memories."""

    name = "memory_list"
    description = (
        "List recent memories from long-term storage. "
        "Use when the user asks 'what do you remember about me?' or 'show me your memory'."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum number of memories to list (default 10, max 50).",
            }
        },
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        limit = min(int(kwargs.get("limit", 10)), 50)
        mgr = get_memory_manager()
        memories = mgr.list_memories(limit=limit)

        if not memories:
            return _ok({"memories": [], "count": 0}, "No memories stored yet.")

        lines = [f"I have {len(memories)} memories:"]
        items = []
        for m in memories:
            line = f"  [{m.id[:8]}] [{m.memory_type.value}] {m.content[:80]}"
            lines.append(line)
            items.append({
                "id": m.id,
                "type": m.memory_type.value,
                "content": m.content,
                "importance": m.importance,
            })
        return _ok({"memories": items, "count": len(items)}, "\n".join(lines))


# ─────────────────────────────────────────────────────────────────────────────
# memory_stats
# ─────────────────────────────────────────────────────────────────────────────

class MemoryStatsTool(BaseTool):
    """Return statistics about Harma's long-term memory store."""

    name = "memory_stats"
    description = "Return statistics about the long-term memory system."
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        mgr = get_memory_manager()
        stats = mgr.stats()
        summary = (
            f"Memory: {stats.get('active', 0)} active / "
            f"{stats.get('total', 0)} total  |  "
            f"Types: {stats.get('by_type', {})}"
        )
        return _ok(stats, summary)


# ─────────────────────────────────────────────────────────────────────────────
# memory_forget_all (HIGH_RISK)
# ─────────────────────────────────────────────────────────────────────────────

class MemoryForgetAllTool(BaseTool):
    """Delete ALL long-term memories. This is irreversible. HIGH RISK."""

    name = "memory_forget_all"
    description = (
        "Delete ALL stored memories. This is a destructive operation. "
        "Only use when the user explicitly confirms they want to clear all memory. "
        "Always ask for confirmation before calling this."
    )
    permission_level = PermissionLevel.HIGH_RISK
    parameters = {
        "type": "object",
        "properties": {
            "confirm": {
                "type": "boolean",
                "description": "Must be true. Confirmation that the user wants all memories deleted.",
            }
        },
        "required": ["confirm"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not kwargs.get("confirm", False):
            return _err("Deletion not confirmed. Set confirm=true to proceed.")
        mgr = get_memory_manager()
        count = mgr.forget_all()
        return _ok(
            {"deleted_count": count},
            f"Cleared {count} memories from long-term storage.",
        )


# Aliases for convenience
RememberTool = MemoryRememberTool
SearchMemoryTool = MemorySearchTool
RecallMemoryTool = MemoryRecallTool
GetMemoryTool = MemoryRecallTool
UpdateMemoryTool = MemoryUpdateTool
ForgetMemoryTool = MemoryForgetTool
ForgetMatchingMemoryTool = MemoryForgetQueryTool
ForgetAllMemoriesTool = MemoryForgetAllTool
ListMemoriesTool = MemoryListTool


def get_memory_tools() -> list[BaseTool]:
    """Return all memory tool instances for registration."""
    return [
        MemoryRememberTool(),
        MemorySearchTool(),
        MemoryRecallTool(),
        MemoryUpdateTool(),
        MemoryForgetTool(),
        MemoryForgetQueryTool(),
        MemoryListTool(),
        MemoryStatsTool(),
        MemoryForgetAllTool(),
    ]

