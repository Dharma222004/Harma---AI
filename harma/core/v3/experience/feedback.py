"""
Harma Runtime V3 — User Feedback Learning (spec §9E, §40)

Converts explicit user corrections into structured Correction experiences.

Trust boundary:
  * Only the user's own request text is ever parsed — never tool output, web pages,
    MCP responses or other external content.
  * Grammar is conservative and fully anchored; anything ambiguous is NOT treated as feedback.
  * Learned confirmation policies can only TIGHTEN security, never relax it.
  * No sensitive personal attributes are inferred.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from harma.core.v3.experience.models import Correction, ExperienceSource

_NAME = r"[\w][\w .+\-]{0,40}?"
_END = r"\s*[.!]*\s*$"

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("prefer", re.compile(
        rf"^(?:no[,.!]?\s+)?(?:please\s+)?use\s+(?P<subject>{_NAME})\s+instead(?:\s+of\s+(?P<replaces>{_NAME}))?(?:\s+next\s+time)?{_END}",
        re.I)),
    ("prefer", re.compile(
        rf"^(?:from\s+now\s+on,?\s+)?(?:always|please\s+always)\s+use\s+(?P<subject>{_NAME})(?:\s+instead\s+of\s+(?P<replaces>{_NAME}))?{_END}",
        re.I)),
    ("avoid", re.compile(
        rf"^(?:no[,.!]?\s+)?(?:please\s+)?(?:don'?t|do\s+not|never)\s+use\s+(?P<subject>{_NAME})(?:\s+(?:anymore|again|next\s+time))?{_END}",
        re.I)),
    ("require_confirmation", re.compile(
        rf"^(?:from\s+now\s+on,?\s+)?(?:please\s+)?always\s+(?:ask|check\s+with|confirm\s+with)\s+(?:me\s+)?before\s+(?P<subject>{_NAME}){_END}",
        re.I)),
    ("reject_last", re.compile(
        r"^(?:no[,.!]?\s+)?(?:that|this|it)\s+(?:was|is)(?:n'?t|\s+not)\s+(?:the\s+)?(?:correct|right)(?:\s+[\w ]{1,40})?\s*[.!]*\s*$",
        re.I)),
    ("reject_last", re.compile(r"^(?:no[,.!]?\s+)?(?:that'?s|that\s+is)\s+wrong\s*[.!]*\s*$", re.I)),
    ("confirm_last", re.compile(
        r"^(?:yes[,.!]?\s+)?(?:that'?s|that\s+is|this\s+is)\s+(?:correct|right|perfect|exactly\s+right)\s*[.!]*\s*$", re.I)),
    ("confirm_last", re.compile(r"^(?:yes[,.!]?\s+)?do\s+it\s+(?:this|that)\s+way\s+next\s+time\s*[.!]*\s*$", re.I)),
]

_APP_ARG_HINTS = ("application", "app", "browser", "package", "program")


def parse_feedback(text: str) -> Optional[Correction]:
    """Return a Correction for explicit feedback statements, else None."""
    t = (text or "").strip()
    if not t or len(t) > 160 or "\n" in t:
        return None
    for kind, pat in _PATTERNS:
        m = pat.match(t)
        if not m:
            continue
        gd = m.groupdict()
        subject = (gd.get("subject") or "").strip().strip(".!").lower()
        replaces = (gd.get("replaces") or "").strip().strip(".!").lower()
        return Correction(kind=kind, subject=subject, replaces=replaces, user_statement=t,
                          source=ExperienceSource.EXPLICIT_USER_CORRECTION.value, confidence=0.95)
    return None


def infer_replaced_subject(correction: Correction, last_run: Optional[dict[str, Any]]) -> Correction:
    """For 'use X instead', infer what X replaces from the previous run's application-like arguments."""
    if correction.kind != "prefer" or correction.replaces or not last_run:
        return correction
    for step in last_run.get("steps", []):
        for k, v in (step.get("arguments") or {}).items():
            if isinstance(v, str) and any(h in k.lower() for h in _APP_ARG_HINTS):
                if v.strip().lower() != correction.subject:
                    correction.replaces = v.strip().lower()
                    correction.previous_behavior = f"{step.get('tool')}({k}={v})"
                    return correction
    return correction


# ── Applying corrections ──────────────────────────────────────────────────────

def apply_corrections(steps: list[dict[str, Any]], corrections: list[Correction]) -> tuple[list[dict[str, Any]], str]:
    """
    Apply prefer/avoid corrections to instantiated steps.

    Returns (steps, blocked_reason). A non-empty blocked_reason means the steps use something
    the user explicitly asked to avoid and must not be reused as-is.
    """
    prefer = {c.replaces: c.subject for c in corrections if c.kind == "prefer" and c.replaces and c.subject}
    avoid = {c.subject for c in corrections if c.kind == "avoid" and c.subject}
    out: list[dict[str, Any]] = []
    for st in steps:
        args = {}
        for k, v in (st.get("arguments") or {}).items():
            if isinstance(v, str) and v.strip().lower() in prefer:
                v = prefer[v.strip().lower()]
                if v and v[0].isalpha():
                    v = v[0].upper() + v[1:]
            args[k] = v
        out.append({**st, "arguments": args})
    for st in out:
        for v in st["arguments"].values():
            if isinstance(v, str) and v.strip().lower() in avoid:
                return out, f"uses '{v}', which you asked me not to use"
    return out, ""


def _stem(word: str) -> str:
    w = word.lower()
    for suf in ("ing", "es", "s", "ed", "e"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[: -len(suf)]
            break
    return w[:4]


def requires_confirmation(tool_name: str, corrections: list[Correction]) -> bool:
    """Learned 'always ask me before <verb>' policies (tighten-only)."""
    tool_tokens = {_stem(t) for t in re.split(r"[_.\-]", tool_name) if len(t) >= 3}
    for c in corrections:
        if c.kind != "require_confirmation" or not c.subject:
            continue
        subj_tokens = {_stem(t) for t in re.findall(r"[a-z]+", c.subject.lower()) if len(t) >= 3}
        if subj_tokens & tool_tokens or c.subject.lower() in ("anything", "everything", "acting", "any action"):
            return True
    return False


def describe(correction: Correction) -> str:
    """Deterministic acknowledgement for a stored correction."""
    k, s, r = correction.kind, correction.subject, correction.replaces
    if k == "prefer":
        return f"Got it — I'll use {s} instead of {r} from now on." if r else f"Got it — I'll prefer {s} from now on."
    if k == "avoid":
        return f"Understood — I won't use {s}."
    if k == "require_confirmation":
        return f"Understood — I'll always ask you before {s}."
    if k == "reject_last":
        return "Thanks for the correction — I've marked that approach as incorrect and won't reuse it blindly."
    if k == "confirm_last":
        return "Great — I'll remember that approach worked."
    return "Noted."
