"""
Harma Long-Term Memory — Exceptions — Phase 5
"""
from __future__ import annotations


class MemoryError(Exception):
    """Base for all long-term memory errors."""


class MemoryStoreError(MemoryError):
    """Storage-layer failure (SQLite I/O, etc.)."""


class MemoryNotFoundError(MemoryError):
    """Requested memory ID does not exist."""


class MemoryConflictError(MemoryError):
    """Attempted operation conflicts with existing memory state."""


class MemoryPrivacyError(MemoryError):
    """Content rejected by privacy / secret-detection checks."""


class MemoryValidationError(MemoryError):
    """Memory content or metadata failed validation."""


class MemoryPermissionError(MemoryError):
    """Operation not permitted under current permission config."""


class MemoryExtractionError(MemoryError):
    """Memory extraction pipeline failure."""


class MemoryRetrievalError(MemoryError):
    """Retrieval / search failure."""
