"""
Harma Runtime V3 — Adaptive Execution + Experience Learning.

Opt-in via ``HARMA_RUNTIME=v3`` (or ``agent.runtime: v3`` in config). The existing
ExecutionEngine remains the default and the fallback.

Lifecycle: understand → retrieve experience → choose strategy → execute → observe →
verify → learn → reuse. ``HarmaRunner`` is the single authoritative run owner.
"""

__all__ = ["HarmaRunner", "HarmaRunState"]


def __getattr__(name):  # Lazy to keep import of the package cheap
    if name == "HarmaRunner":
        from harma.core.v3.runner import HarmaRunner
        return HarmaRunner
    if name == "HarmaRunState":
        from harma.core.v3.state import HarmaRunState
        return HarmaRunState
    raise AttributeError(name)
