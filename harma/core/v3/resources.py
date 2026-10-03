"""
Harma Runtime V3 — Resource Manager (spec §31, §32)

Serialises access to exclusive resources so concurrent runs (e.g. a scheduled task and an
interactive request) never fight over the same keyboard/mouse, browser, Android device or
MCP connection. Read-only tools take no lock.

Session reuse: the browser controller, Android manager, MCP integration manager and LLM
client are process-wide singletons in Harma; the runtime reuses them and never reconnects
per operation.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

RESOURCES = ("desktop_input", "browser_session", "android_device", "mcp")


class ResourceManager:
    def __init__(self) -> None:
        self._locks: dict[tuple[int, str], asyncio.Lock] = {}
        self._holders: dict[str, dict[str, Any]] = {}

    def _lock(self, resource: str) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        key = (id(loop), resource)
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    @asynccontextmanager
    async def acquire(self, resource: Optional[str], owner: str = "", timeout: float = 120.0) -> AsyncIterator[float]:
        """Hold `resource` for the duration of the block. Yields seconds spent waiting."""
        if not resource:
            yield 0.0
            return
        lock = self._lock(resource)
        t0 = time.perf_counter()
        await asyncio.wait_for(lock.acquire(), timeout=timeout)
        waited = time.perf_counter() - t0
        self._holders[resource] = {"owner": owner, "since": time.time()}
        try:
            yield waited
        finally:
            self._holders.pop(resource, None)
            lock.release()

    def status(self) -> dict[str, Any]:
        return {r: self._holders.get(r) for r in RESOURCES}


_MANAGER: Optional[ResourceManager] = None


def get_resource_manager() -> ResourceManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = ResourceManager()
    return _MANAGER
