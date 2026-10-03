"""
Harma Runtime V3 — Verification Engine (spec §27, §29)

ACTION SUCCESS ≠ GOAL SUCCESS. A step only counts as achieved when independent evidence
confirms its intended effect.

Policy (cheapest sufficient evidence first):
  1. Tool failed                                    → FAILED
  2. Tool self-reports `verified` / evidence        → VERIFIED / FAILED
  3. Tool-specific verifier (window, keyboard, page, device, file) → VERIFIED / FAILED / INCONCLUSIVE
  4. Read-only tool (result is the answer)          → NOT_REQUIRED
  5. System-of-record domains (memory, tasks)       → VERIFIED from the authoritative result
  6. Otherwise                                      → INCONCLUSIVE (runner re-observes once, then UNVERIFIED)

Verifiers are injectable; system verifiers (real desktop/browser) can be disabled for tests.
"""

from __future__ import annotations

import inspect
import os
import re
import time
from enum import Enum
from typing import Any, Callable, Optional
from urllib.parse import unquote_plus

from harma.config.logging_config import get_logger
from harma.core.v3 import toolmeta
from harma.core.v3.state import PlanStep

log = get_logger(__name__)


class Verdict(str, Enum):
    VERIFIED = "verified"
    INCONCLUSIVE = "inconclusive"
    FAILED = "failed"
    NOT_REQUIRED = "not_required"


Verifier = Callable[[PlanStep, Any, dict[str, Any]], Any]   # → (Verdict, detail) or awaitable thereof


def _vr_to_verdict(vr: Any) -> tuple[Verdict, str]:
    if vr is None:
        return Verdict.INCONCLUSIVE, "no verifier result"
    if getattr(vr, "verified", False):
        return Verdict.VERIFIED, str(getattr(vr, "detail", ""))
    if getattr(vr, "failed", False):
        return Verdict.FAILED, str(getattr(vr, "detail", ""))
    return Verdict.INCONCLUSIVE, str(getattr(vr, "detail", ""))


# ── System verifiers (real environment) ──────────────────────────────────────

async def _v_window_opened(step: PlanStep, outcome: Any, obs: dict[str, Any]):
    from harma.computer.verification import get_verifier
    app = step.arguments.get("application_name") or step.arguments.get("name") or ""
    return _vr_to_verdict(await get_verifier().verify_window_opened(application_name=app, tool_succeeded=True, timeout=8.0))


async def _v_window_focused(step: PlanStep, outcome: Any, obs: dict[str, Any]):
    from harma.computer.verification import get_verifier
    frag = (step.arguments.get("window_title") or step.arguments.get("title_fragment")
            or step.arguments.get("application_name") or obs.get("app", ""))
    return _vr_to_verdict(await get_verifier().verify_window_focused(window_fragment=frag, tool_succeeded=True, timeout=3.0))


async def _v_keyboard(step: PlanStep, outcome: Any, obs: dict[str, Any]):
    from harma.computer.verification import get_verifier
    expected = step.arguments.get("text") if step.tool == "type_text" else None
    frag = obs.get("app") or obs.get("active_window", "")
    return _vr_to_verdict(await get_verifier().verify_keyboard_input(
        action_name=step.tool, tool_succeeded=True, expected_text=expected, window_fragment=frag))


def _v_browser_page(step: PlanStep, outcome: Any, obs: dict[str, Any]):
    url, title = obs.get("current_url", ""), obs.get("page_title", "")
    if not url:
        return Verdict.INCONCLUSIVE, "no live page state"
    target = str(step.arguments.get("url") or step.arguments.get("query") or "")
    if not target:
        return Verdict.VERIFIED, f"page loaded: {url}"
    t_low = unquote_plus(target).lower()
    page = f"{unquote_plus(url)} {title}".lower()
    domain = re.sub(r"^https?://(www\.)?", "", t_low).split("/")[0]
    tokens = [w for w in re.findall(r"[a-z0-9]{3,}", t_low) if w not in ("https", "http", "www", "com")]
    if (domain and domain in page) or (tokens and sum(w in page for w in tokens) >= max(1, len(tokens) // 2)):
        return Verdict.VERIFIED, f"page reflects target: {url} '{title}'"
    return Verdict.INCONCLUSIVE, f"page {url} does not clearly reflect '{target}'"


def _v_screenshot(step: PlanStep, outcome: Any, obs: dict[str, Any]):
    data = getattr(outcome, "data", None)
    path = (data or {}).get("path") if isinstance(data, dict) else None
    if not path:
        m = re.search(r"([A-Za-z]:\\[^\s'\"]+\.(?:png|jpg)|/[^\s'\"]+\.(?:png|jpg))", str(getattr(outcome, "result", "")))
        path = m.group(1) if m else None
    if path and os.path.exists(path):
        return Verdict.VERIFIED, f"screenshot saved: {path}"
    return Verdict.NOT_REQUIRED, "screenshot result returned"


def system_verifiers() -> dict[str, Verifier]:
    return {
        "open_application": _v_window_opened,
        "focus_application": _v_window_focused,
        "type_text": _v_keyboard,
        "press_key": _v_keyboard,
        "hotkey": _v_keyboard,
        "navigate_to": _v_browser_page,
        "search_web": _v_browser_page,
        "take_screenshot": _v_screenshot,
    }


class VerificationEngine:
    def __init__(self, ctx: Any = None, use_system_verifiers: bool = True,
                 verifiers: Optional[dict[str, Verifier]] = None) -> None:
        self.ctx = ctx
        self.verifiers: dict[str, Verifier] = system_verifiers() if use_system_verifiers else {}
        if use_system_verifiers:
            self.verifiers["android.launch_app"] = self._v_android_launch
        if verifiers:
            self.verifiers.update(verifiers)

    async def _v_android_launch(self, step: PlanStep, outcome: Any, obs: dict[str, Any]):
        target = str(step.arguments.get("package") or step.arguments.get("app") or step.arguments.get("app_name") or "")
        if not target or self.ctx is None or self.ctx.registry.get("android.current_app") is None:
            return Verdict.INCONCLUSIVE, "no device state probe"
        res = await self.ctx.registry.call("android.current_app")
        current = f"{getattr(res, 'output', '')} {getattr(res, 'data', '')}".lower()
        if target.lower() in current:
            return Verdict.VERIFIED, f"foreground app matches {target}"
        return Verdict.INCONCLUSIVE, f"foreground app does not match {target}"

    async def verify(self, step: PlanStep, outcome: Any, obs: dict[str, Any]) -> tuple[Verdict, str, list[dict[str, Any]]]:
        t0 = time.perf_counter()
        verdict, detail = await self._verify(step, outcome, obs)
        evidence = [{"type": "verification", "verdict": verdict.value, "detail": detail[:300],
                     "ms": round((time.perf_counter() - t0) * 1000, 2)}]
        return verdict, detail, evidence

    async def _verify(self, step: PlanStep, outcome: Any, obs: dict[str, Any]) -> tuple[Verdict, str]:
        if not getattr(outcome, "ok", False):
            return Verdict.FAILED, str((getattr(outcome, "error", None) or {}).get("message", "tool failed"))
        if getattr(outcome, "action_state", "") == "skipped_duplicate":
            prior = getattr(outcome, "verification_state", None)
            val = getattr(prior, "value", prior)
            return (Verdict.VERIFIED if val == "verified" else Verdict.NOT_REQUIRED if val == "not_required"
                    else Verdict.INCONCLUSIVE), "duplicate side effect skipped; prior result stands"

        data = getattr(outcome, "data", None)
        if isinstance(data, dict) and "verified" in data and data["verified"] is not None:
            if data["verified"]:
                return Verdict.VERIFIED, str(data.get("evidence", "tool reported verified effect"))
            return Verdict.FAILED, str(data.get("evidence", "tool reported effect not achieved"))

        verifier = self.verifiers.get(step.tool)
        if verifier is not None:
            try:
                res = verifier(step, outcome, obs)
                if inspect.isawaitable(res):
                    res = await res
                verdict, detail = res
                if verdict != Verdict.INCONCLUSIVE:
                    return verdict, detail
                inconclusive_detail = detail
            except Exception as exc:
                log.debug("[V3][VERIFY] verifier error for %s: %s", step.tool, exc)
                inconclusive_detail = f"verifier error: {exc}"
        else:
            inconclusive_detail = ""

        if toolmeta.is_read_only(step.tool, self.ctx.registry.get(step.tool) if self.ctx else None):
            return Verdict.NOT_REQUIRED, "read-only result is the answer"
        if toolmeta.domain_of(step.tool) in ("memory", "scheduled_tasks"):
            return Verdict.VERIFIED, "system-of-record confirmed the change"
        return Verdict.INCONCLUSIVE, inconclusive_detail or "no independent evidence of the effect"
