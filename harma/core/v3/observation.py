"""
Harma Runtime V3 — Observation Engine (spec §28)

Uses the CHEAPEST sufficient evidence, following the hierarchy:
  1 tool result → 2 structured state → 3 DOM → 4 accessibility tree → 5 UI hierarchy
  → 6 lightweight state query → 7 screenshot → 8 vision
No screenshot is taken per action; read-only and self-reporting tools need no probe at all.

System probes (active window, browser page) are injectable so tests never touch the desktop.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import time
from typing import Any, Awaitable, Callable, Optional

from harma.config.logging_config import get_logger
from harma.core.v3 import toolmeta
from harma.core.v3.state import HarmaRunState, PlanStep

log = get_logger(__name__)

Probe = Callable[[], Any]


def _system_window_probe() -> dict[str, Any]:
    from harma.computer.windows import get_active_window_info
    info = get_active_window_info() or {}
    return {"active_window": info.get("title", ""), "app": info.get("app", "")}


async def _system_browser_probe() -> dict[str, Any]:
    from harma.browser.controller import get_browser_controller
    ctrl = get_browser_controller()
    if not (ctrl and ctrl.is_open and getattr(ctrl, "_session", None) and ctrl._session.active_page):
        return {}
    page = ctrl._session.active_page
    out = {"current_url": page.url}
    try:
        out["page_title"] = await page.title()
    except Exception:
        pass
    return out


async def _call(probe: Probe) -> dict[str, Any]:
    res = probe()
    if inspect.isawaitable(res):
        res = await res
    return res or {}


def observation_fingerprint(obs: dict[str, Any]) -> str:
    key = "|".join(str(obs.get(k, "")) for k in ("active_window", "app", "current_url", "page_title"))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


class ObservationEngine:
    def __init__(self, use_system_probes: bool = True, probes: Optional[dict[str, Probe]] = None) -> None:
        self.probes: dict[str, Probe] = {}
        if use_system_probes:
            self.probes = {"window": _system_window_probe, "browser": _system_browser_probe}
        if probes:
            self.probes.update(probes)

    async def observe(self, state: HarmaRunState, step: PlanStep, outcome: Any) -> dict[str, Any]:
        t0 = time.perf_counter()
        obs: dict[str, Any] = {"tool": step.tool, "step_id": step.step_id, "t": time.time(),
                               "tool_succeeded": bool(getattr(outcome, "ok", False))}
        try:
            domain = toolmeta.domain_of(step.tool)
            if not obs["tool_succeeded"] or toolmeta.is_read_only(step.tool) or getattr(outcome, "evidence", None) \
                    or domain in ("memory", "scheduled_tasks"):
                obs["level"] = 1
                obs["evidence"] = "tool_result"
                obs["tool_output"] = str(getattr(outcome, "result", ""))[:200]
            elif domain == "computer" and "window" in self.probes:
                obs["level"] = 6
                obs.update(await asyncio.wait_for(_call(self.probes["window"]), timeout=3.0))
            elif domain == "browser" and "browser" in self.probes:
                obs["level"] = 3
                obs.update(await asyncio.wait_for(_call(self.probes["browser"]), timeout=3.0))
            else:
                obs["level"] = 1
                obs["evidence"] = "tool_result"
                obs["tool_output"] = str(getattr(outcome, "result", ""))[:200]
        except Exception as exc:
            log.debug("[V3][OBSERVE] probe failed for %s: %s", step.tool, exc)
            obs["probe_error"] = str(exc)[:120]
        obs["fingerprint"] = observation_fingerprint(obs)
        obs["observation_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        state.observations.append(obs)
        if len(state.observations) > 50:
            del state.observations[:-50]
        return obs
