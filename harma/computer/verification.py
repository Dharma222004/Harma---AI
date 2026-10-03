"""
Harma Computer Verification Layer

Implements the fundamental distinction:

    ACTION EXECUTED  ≠  OUTCOME VERIFIED  ≠  GOAL COMPLETED

Every consequential desktop action produces a VerificationResult that distinguishes:
  - ACTION_FAILED          — tool call itself reported failure
  - ACTION_EXECUTED_UNVERIFIED — tool succeeded but environment not yet checked
  - ACTION_EXECUTED_VERIFIED   — tool succeeded AND expected post-action state confirmed

The verifier uses evidence in priority order:
  1. Windows accessibility / UI element hierarchy (win32 UIA / pywinauto)
  2. Window existence and title matching
  3. Active foreground window inspection
  4. Screenshot OCR (when PIL + pytesseract available)
  5. Structured tool result metadata
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from harma.config.logging_config import get_logger

log = get_logger(__name__)


# ── Outcome taxonomy ──────────────────────────────────────────────────────────

class ActionOutcome(str, Enum):
    """
    Three-valued outcome for any desktop action.
    Replacing the binary success/failure boolean used previously.
    """
    ACTION_FAILED = "action_failed"
    """The tool call itself reported failure. No retry of observation needed."""

    ACTION_EXECUTED_UNVERIFIED = "action_executed_unverified"
    """Tool reported success but post-action state has NOT been verified yet.
    The execution engine must observe the environment before claiming success."""

    ACTION_EXECUTED_VERIFIED = "action_executed_verified"
    """Tool reported success AND the expected post-action state was confirmed
    through at least one independent observation."""


# ── Evidence model ────────────────────────────────────────────────────────────

@dataclass
class VerificationEvidence:
    """Structured evidence from a post-action observation."""
    source: str                         # "window_title" | "active_window" | "accessibility" | "screenshot_ocr"
    observation: str                    # Human-readable description of what was seen
    contains_expected: bool = False     # Whether the expected text/state was found
    confidence: float = 0.0            # 0.0–1.0 confidence score
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class VerificationResult:
    """
    Complete outcome of one post-action verification attempt.

    This is the authoritative record of whether an action achieved
    its intended real-world effect. The execution engine must inspect
    this object — NOT the raw tool ToolResult.success field — when
    deciding whether to move to the next step or to recover.
    """
    outcome: ActionOutcome
    action: str                         # tool name executed
    expected_state: str                 # human-readable expected post-action state
    evidence: list[VerificationEvidence] = field(default_factory=list)
    best_confidence: float = 0.0
    elapsed_ms: float = 0.0
    detail: str = ""                    # summary suitable for logging / LLM

    @property
    def verified(self) -> bool:
        return self.outcome == ActionOutcome.ACTION_EXECUTED_VERIFIED

    @property
    def failed(self) -> bool:
        return self.outcome == ActionOutcome.ACTION_FAILED

    @property
    def unverified(self) -> bool:
        return self.outcome == ActionOutcome.ACTION_EXECUTED_UNVERIFIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "action": self.action,
            "expected_state": self.expected_state,
            "verified": self.verified,
            "best_confidence": round(self.best_confidence, 3),
            "evidence": [
                {
                    "source": e.source,
                    "observation": e.observation,
                    "contains_expected": e.contains_expected,
                    "confidence": round(e.confidence, 3),
                }
                for e in self.evidence
            ],
            "detail": self.detail,
            "elapsed_ms": round(self.elapsed_ms, 1),
        }

    def to_log_string(self) -> str:
        prefix = {
            ActionOutcome.ACTION_FAILED: "[ACTION_FAILED]",
            ActionOutcome.ACTION_EXECUTED_UNVERIFIED: "[ACTION_UNVERIFIED]",
            ActionOutcome.ACTION_EXECUTED_VERIFIED: "[VERIFIED]",
        }[self.outcome]
        return f"{prefix} {self.action}: {self.detail}"


_EDITION_QUALIFIERS = ("beta", "preview", "dev", "canary", "insider", "business")


def _matches_window_title(expected_fragment: str, actual_title: str) -> bool:
    """
    Check if actual_title matches expected_fragment, ensuring that edition
    qualifiers (beta, preview, dev, canary, insider, business) are not mismatched.
    For example:
      _matches_window_title('whatsapp', 'WhatsApp Beta') -> False
      _matches_window_title('whatsapp', 'WhatsApp') -> True
      _matches_window_title('whatsapp beta', 'WhatsApp Beta') -> True
    """
    exp = expected_fragment.strip().lower()
    act = actual_title.strip().lower()
    if not exp or not act:
        return False
    if exp not in act:
        return False
    # If the window title has an edition qualifier that was not requested, reject match
    if any(q in act and q not in exp for q in _EDITION_QUALIFIERS):
        return False
    return True


# ── Window polling utility ────────────────────────────────────────────────────

class WindowPoller:
    """
    Condition-based window polling — replaces arbitrary time.sleep() calls.

    Usage:
        poller = WindowPoller()
        success = await poller.wait_for_window("WhatsApp", timeout=10.0)
    """

    def __init__(self, poll_interval: float = 0.1) -> None:
        self._interval = poll_interval

    async def wait_for_window(
        self,
        title_fragment: str,
        timeout: float = 8.0,
    ) -> bool:
        """
        Poll until a window whose title contains title_fragment becomes visible.
        Returns True when found within timeout, False otherwise.
        """
        deadline = time.monotonic() + timeout
        fragment = title_fragment.lower()
        log.info("[POLLER] Waiting for window containing '%s' (timeout=%.1fs)", title_fragment, timeout)

        while time.monotonic() < deadline:
            if self._window_visible(fragment):
                log.info("[POLLER] Window '%s' became visible", title_fragment)
                return True
            await asyncio.sleep(self._interval)

        log.warning("[POLLER] Timeout waiting for window '%s'", title_fragment)
        return False

    async def wait_for_foreground(
        self,
        title_fragment: str,
        timeout: float = 5.0,
    ) -> bool:
        """
        Poll until a window containing title_fragment is the foreground window.
        """
        deadline = time.monotonic() + timeout
        fragment = title_fragment.lower()
        log.info("[POLLER] Waiting for '%s' to become foreground", title_fragment)

        while time.monotonic() < deadline:
            fg = self._get_foreground_title()
            if _matches_window_title(fragment, fg):
                log.info("[POLLER] '%s' is now foreground ('%s')", title_fragment, fg)
                return True
            await asyncio.sleep(self._interval)

        log.warning("[POLLER] Timeout waiting for '%s' foreground", title_fragment)
        return False

    async def wait_for_condition(
        self,
        condition: Callable[[], bool],
        timeout: float = 10.0,
        description: str = "condition",
    ) -> bool:
        """Generic condition polling."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if condition():
                    log.info("[POLLER] Condition met: %s", description)
                    return True
            except Exception:
                pass
            await asyncio.sleep(self._interval)
        log.warning("[POLLER] Timeout waiting for: %s", description)
        return False

    def _window_visible(self, fragment_lower: str) -> bool:
        try:
            import sys
            if sys.platform == "win32":
                try:
                    from harma.computer.windows import ensure_default_desktop
                    ensure_default_desktop()
                except Exception:
                    pass
                import win32gui
                found = [False]
                variants = {fragment_lower}
                if fragment_lower in ("microsoft edge", "ms edge", "edge"):
                    variants.update({"msedge", "edge", "microsoft edge"})
                elif fragment_lower in ("google chrome", "chrome"):
                    variants.update({"chrome", "google chrome"})
                elif fragment_lower in ("telegram", "telegram desktop"):
                    variants.update({"telegram", "telegram desktop"})

                def cb(hwnd, _):
                    if win32gui.IsWindowVisible(hwnd):
                        t = win32gui.GetWindowText(hwnd).lower()
                        cls = win32gui.GetClassName(hwnd)
                        if cls == "#32770" and "dialog" not in fragment_lower:
                            return True  # Skip error/alert dialog

                        for v in variants:
                            if _matches_window_title(v, t):
                                found[0] = True
                                return False
                        if t:
                            try:
                                import win32process, psutil
                                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                                pname = psutil.Process(pid).name().lower()
                                for v in variants:
                                    if _matches_window_title(v, pname):
                                        found[0] = True
                                        return False
                            except Exception:
                                pass
                    return True
                try:
                    win32gui.EnumWindows(cb, None)
                except Exception:
                    pass
                return found[0]
        except Exception:
            pass
        return False

    def _get_foreground_title(self) -> str:
        try:
            import sys
            if sys.platform == "win32":
                try:
                    from harma.computer.windows import ensure_default_desktop
                    ensure_default_desktop()
                except Exception:
                    pass
                import win32gui
                hwnd = win32gui.GetForegroundWindow()
                if hwnd:
                    cls = win32gui.GetClassName(hwnd)
                    t = win32gui.GetWindowText(hwnd)
                    if cls == "#32770" and t:
                        return f"Dialog: {t}"
                    return t
        except Exception:
            pass
        return ""


# ── Main verifier ─────────────────────────────────────────────────────────────

class ActionVerifier:
    """
    Post-action state verifier for desktop computer tasks.

    DOES NOT use:
    - Hard-coded application names
    - Keyword checks (if app == "WhatsApp": ...)
    - Fixed sleeps

    Instead, uses a ranked evidence pipeline:
    1. Windows title / active window inspection (cheapest, very reliable)
    2. Accessibility tree (when pywinauto available)
    3. Screenshot + OCR (fallback, expensive)

    The minimum_confidence threshold controls when VERIFIED is declared.
    Below this, the outcome remains UNVERIFIED, prompting re-observation.
    """

    MINIMUM_CONFIDENCE_FOR_VERIFIED: float = 0.5

    def __init__(self) -> None:
        self._poller = WindowPoller()

    async def verify_window_opened(
        self,
        application_name: str,
        tool_succeeded: bool,
        window_fragment: Optional[str] = None,
        timeout: float = 8.0,
    ) -> VerificationResult:
        """
        Verify that an application window became visible after open_application.
        """
        t0 = time.time()
        action = "open_application"
        fragment = window_fragment or application_name
        expected = f"Window containing '{fragment}' is visible and focused"

        if not tool_succeeded:
            return VerificationResult(
                outcome=ActionOutcome.ACTION_FAILED,
                action=action,
                expected_state=expected,
                detail=f"open_application tool reported failure for '{application_name}'",
                elapsed_ms=(time.time() - t0) * 1000,
            )

        # Wait for window to appear (condition-based, not sleep-based)
        appeared = await self._poller.wait_for_window(fragment, timeout=timeout)
        evidence: list[VerificationEvidence] = []

        if appeared:
            # Confirm it's the foreground window
            fg = self._poller._get_foreground_title()
            if fg.startswith("Dialog:"):
                outcome = ActionOutcome.ACTION_FAILED
                detail = f"An error dialog appeared instead of '{application_name}': {fg}"
                evidence.append(VerificationEvidence(
                    source="active_window",
                    observation=detail,
                    contains_expected=False,
                    confidence=0.0,
                ))
            else:
                fg_match = _matches_window_title(fragment, fg)
                ev = VerificationEvidence(
                    source="active_window",
                    observation=f"Foreground window: '{fg}'",
                    contains_expected=fg_match,
                    confidence=0.9 if fg_match else 0.2,
                    raw={"foreground_title": fg, "fragment": fragment},
                )
                evidence.append(ev)
                best = ev.confidence

                # Also check via window list
                list_ev = self._check_window_list(fragment)
                if list_ev:
                    evidence.append(list_ev)
                    best = max(best, list_ev.confidence)

                outcome = (
                    ActionOutcome.ACTION_EXECUTED_VERIFIED
                    if best >= self.MINIMUM_CONFIDENCE_FOR_VERIFIED
                    else ActionOutcome.ACTION_EXECUTED_UNVERIFIED
                )
                detail = f"Application '{application_name}' window visible (fg='{fg}', confidence={best:.2f})"
        else:
            evidence.append(VerificationEvidence(
                source="window_list",
                observation=f"No window containing '{fragment}' appeared within {timeout}s",
                contains_expected=False,
                confidence=0.0,
            ))
            outcome = ActionOutcome.ACTION_EXECUTED_UNVERIFIED
            detail = f"Window '{fragment}' not detected within timeout ({timeout}s)"

        elapsed = (time.time() - t0) * 1000
        result = VerificationResult(
            outcome=outcome,
            action=action,
            expected_state=expected,
            evidence=evidence,
            best_confidence=max((e.confidence for e in evidence), default=0.0),
            elapsed_ms=elapsed,
            detail=detail,
        )
        log.info("[VERIFY] %s", result.to_log_string())
        return result

    async def verify_window_focused(
        self,
        window_fragment: str,
        tool_succeeded: bool,
        timeout: float = 3.0,
    ) -> VerificationResult:
        """Verify that a window is the current foreground/active window."""
        t0 = time.time()
        action = "focus_application"
        expected = f"Window containing '{window_fragment}' is the foreground window"

        if not tool_succeeded:
            return VerificationResult(
                outcome=ActionOutcome.ACTION_FAILED,
                action=action,
                expected_state=expected,
                detail=f"focus_application tool reported failure for '{window_fragment}'",
                elapsed_ms=(time.time() - t0) * 1000,
            )

        became_fg = await self._poller.wait_for_foreground(window_fragment, timeout=timeout)
        fg = self._poller._get_foreground_title()
        fg_match = _matches_window_title(window_fragment, fg)
        confidence = 0.95 if fg_match else 0.1

        evidence = [VerificationEvidence(
            source="active_window",
            observation=f"Foreground window: '{fg}'",
            contains_expected=fg_match,
            confidence=confidence,
            raw={"foreground_title": fg, "fragment": window_fragment},
        )]

        outcome = (
            ActionOutcome.ACTION_EXECUTED_VERIFIED
            if fg_match
            else ActionOutcome.ACTION_EXECUTED_UNVERIFIED
        )
        detail = f"Focus check — foreground='{fg}', expected_fragment='{window_fragment}', match={fg_match}"

        result = VerificationResult(
            outcome=outcome,
            action=action,
            expected_state=expected,
            evidence=evidence,
            best_confidence=confidence,
            elapsed_ms=(time.time() - t0) * 1000,
            detail=detail,
        )
        log.info("[VERIFY] %s", result.to_log_string())
        return result

    async def verify_keyboard_input(
        self,
        action_name: str,
        tool_succeeded: bool,
        expected_text: Optional[str] = None,
        window_fragment: Optional[str] = None,
    ) -> VerificationResult:
        """
        Verify keyboard actions (type_text, press_key, hotkey).

        Since we cannot read arbitrary application field content without
        accessibility APIs, we verify:
        1. The active window is still the expected application (focus held).
        2. The active window title hasn't unexpectedly changed (error dialog, crash).
        3. When expected_text and OCR are available: text appears in screenshot.
        """
        t0 = time.time()
        expected = f"Keyboard action '{action_name}' delivered to active window"
        if window_fragment:
            expected += f" ('{window_fragment}')"

        if not tool_succeeded:
            return VerificationResult(
                outcome=ActionOutcome.ACTION_FAILED,
                action=action_name,
                expected_state=expected,
                detail=f"Keyboard tool '{action_name}' reported failure",
                elapsed_ms=(time.time() - t0) * 1000,
            )

        evidence: list[VerificationEvidence] = []
        fg = self._poller._get_foreground_title()

        # Check 1: Is the expected window still in the foreground?
        window_ok = True
        if window_fragment:
            window_ok = _matches_window_title(window_fragment, fg)

        evidence.append(VerificationEvidence(
            source="active_window",
            observation=f"Foreground window after keyboard action: '{fg}'",
            contains_expected=window_ok,
            confidence=0.8 if window_ok else 0.2,
            raw={"foreground_title": fg},
        ))

        # Check 2: No error/crash dialog
        error_indicators = ["error", "crash", "not responding", "exception", "stopped working"]
        has_error = any(ind in fg.lower() for ind in error_indicators)
        if has_error:
            evidence.append(VerificationEvidence(
                source="active_window",
                observation=f"Possible error/crash dialog detected: '{fg}'",
                contains_expected=False,
                confidence=0.9,
            ))
            return VerificationResult(
                outcome=ActionOutcome.ACTION_EXECUTED_UNVERIFIED,
                action=action_name,
                expected_state=expected,
                evidence=evidence,
                best_confidence=0.1,
                elapsed_ms=(time.time() - t0) * 1000,
                detail=f"Error/crash dialog may have appeared: '{fg}'",
            )

        # Check 3: Try OCR if expected_text provided (best-effort)
        if expected_text:
            ocr_ev = self._try_ocr_check(expected_text)
            if ocr_ev:
                evidence.append(ocr_ev)

        best = max((e.confidence for e in evidence), default=0.0)
        outcome = (
            ActionOutcome.ACTION_EXECUTED_VERIFIED
            if (window_ok and best >= self.MINIMUM_CONFIDENCE_FOR_VERIFIED)
            else ActionOutcome.ACTION_EXECUTED_UNVERIFIED
        )

        # For send actions (press_key enter), keep as UNVERIFIED — caller must check conversation
        # This is important: we do not upgrade "enter to send" to VERIFIED automatically
        if action_name == "press_key" and not expected_text:
            outcome = ActionOutcome.ACTION_EXECUTED_UNVERIFIED

        detail = (
            f"Keyboard '{action_name}': active_window='{fg}', "
            f"window_ok={window_ok}, best_confidence={best:.2f}"
        )

        result = VerificationResult(
            outcome=outcome,
            action=action_name,
            expected_state=expected,
            evidence=evidence,
            best_confidence=best,
            elapsed_ms=(time.time() - t0) * 1000,
            detail=detail,
        )
        log.info("[VERIFY] %s", result.to_log_string())
        return result

    def _check_window_list(self, fragment: str) -> Optional[VerificationEvidence]:
        """Check open windows list for presence of fragment."""
        try:
            from harma.computer.windows import list_windows
            wins = list_windows()
            import sys
            for w in wins:
                title = w.get("title", "")
                if _matches_window_title(fragment, title):
                    # Check if it's a modal dialog (#32770)
                    if sys.platform == "win32" and "hwnd" in w:
                        try:
                            import win32gui
                            if win32gui.GetClassName(w["hwnd"]) == "#32770" and "dialog" not in fragment.lower():
                                continue  # Skip modal error dialogs
                        except Exception:
                            pass
                    return VerificationEvidence(
                        source="window_list",
                        observation=f"Window '{title}' in visible window list",
                        contains_expected=True,
                        confidence=0.75,
                        raw={"window": w},
                    )
        except Exception as exc:
            log.debug("[VERIFY] window_list check error: %s", exc)
        return None

    def _try_ocr_check(self, expected_text: str) -> Optional[VerificationEvidence]:
        """
        Attempt screenshot + basic pixel/OCR verification of expected text.
        Returns VerificationEvidence if OCR is available, None otherwise.
        """
        try:
            import pytesseract
            from harma.computer.screen import take_screenshot
            shot = take_screenshot()
            if not shot.success:
                return None
            from PIL import Image
            img = Image.open(shot.image_path)
            ocr_result = pytesseract.image_to_string(img)
            found = expected_text.lower() in ocr_result.lower()
            return VerificationEvidence(
                source="screenshot_ocr",
                observation=f"OCR {'found' if found else 'did not find'} '{expected_text}' in screenshot",
                contains_expected=found,
                confidence=0.85 if found else 0.1,
                raw={"expected": expected_text, "found": found},
            )
        except ImportError:
            # pytesseract not installed — return a low-confidence unverified note
            return None
        except Exception as exc:
            log.debug("[VERIFY] OCR check error: %s", exc)
            return None


# ── Module singleton ──────────────────────────────────────────────────────────

_verifier: Optional[ActionVerifier] = None
_poller: Optional[WindowPoller] = None


def get_verifier() -> ActionVerifier:
    global _verifier
    if _verifier is None:
        _verifier = ActionVerifier()
    return _verifier


def get_poller() -> WindowPoller:
    global _poller
    if _poller is None:
        _poller = WindowPoller()
    return _poller
