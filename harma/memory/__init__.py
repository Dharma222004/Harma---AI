"""
Harma Long-Term Memory & Personal Context Subsystem — Phase 5
"""
from __future__ import annotations

from harma.memory.exceptions import (
    MemoryConflictError,
    MemoryError,
    MemoryExtractionError,
    MemoryNotFoundError,
    MemoryPermissionError,
    MemoryPrivacyError,
    MemoryRetrievalError,
    MemoryStoreError,
    MemoryValidationError,
)
from harma.memory.extraction import MemoryExtractor
from harma.memory.manager import (
    MemoryManager,
    get_memory_manager,
    reset_memory_manager,
)
from harma.memory.models import (
    Memory,
    MemoryCandidate,
    MemoryQuery,
    MemorySearchResult,
    MemorySensitivity,
    MemorySource,
    MemoryStatus,
    MemoryType,
)
from harma.memory.privacy import (
    PrivacyFilter,
    SecretDetector,
    SensitivityClassifier,
    sanitize_for_context,
)
from harma.memory.retrieval import MemoryRetriever
from harma.memory.short_term import ShortTermMemory
from harma.memory.store import SQLiteMemoryStore
from harma.memory.tools import (
    ForgetMemoryTool,
    ForgetAllMemoriesTool,
    ForgetMatchingMemoryTool,
    GetMemoryTool,
    ListMemoriesTool,
    MemoryStatsTool,
    RecallMemoryTool,
    RememberTool,
    SearchMemoryTool,
    UpdateMemoryTool,
    get_memory_tools,
)

__all__ = [
    # Manager
    "MemoryManager",
    "get_memory_manager",
    "reset_memory_manager",
    # Models
    "Memory",
    "MemoryType",
    "MemorySource",
    "MemorySensitivity",
    "MemoryStatus",
    "MemoryQuery",
    "MemorySearchResult",
    "MemoryCandidate",
    # Storage & Retrieval
    "ShortTermMemory",
    "SQLiteMemoryStore",
    "MemoryRetriever",
    "MemoryExtractor",
    # Privacy
    "PrivacyFilter",
    "SecretDetector",
    "SensitivityClassifier",
    "sanitize_for_context",
    # Exceptions
    "MemoryError",
    "MemoryStoreError",
    "MemoryNotFoundError",
    "MemoryConflictError",
    "MemoryPrivacyError",
    "MemoryValidationError",
    "MemoryPermissionError",
    "MemoryExtractionError",
    "MemoryRetrievalError",
    # Tools
    "RememberTool",
    "SearchMemoryTool",
    "RecallMemoryTool",
    "GetMemoryTool",
    "ListMemoriesTool",
    "UpdateMemoryTool",
    "ForgetMemoryTool",
    "ForgetMatchingMemoryTool",
    "ForgetAllMemoriesTool",
    "MemoryStatsTool",
    "get_memory_tools",
]
