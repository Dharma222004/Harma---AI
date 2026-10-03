"""
Harma Runtime V3 — Intent Gateway & Task Router (spec §7, §20, §33)

Cheap, deterministic understanding — no LLM call is spent on classification.

IntentGateway  : normalise the request and classify it into a TaskType.
TaskRouter     : Task → Domain → Capability → relevant tools (reuses the existing
                 capability router so the LLM never sees all tools unnecessarily).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from harma.core.v3 import toolmeta
from harma.core.v3.experience import templates as tpl
from harma.core.v3.experience.feedback import parse_feedback
from harma.core.v3.experience.models import Correction
from harma.core.v3.state import TaskType

_CONVERSATIONAL = re.compile(
    r"^(hi|hello|hey|greetings|thanks|thank you|good\s+(morning|afternoon|evening)|who are you|what is your name|"
    r"how are you)(\s+harma|\s+assistant|\s+there)?\b[!?.]*$", re.I)
_ARITHMETIC = re.compile(r"^what is \d+(\.\d+)?\s*[\+\-\*/x]\s*\d+(\.\d+)?\??$", re.I)
_RECOVERY_Q = re.compile(
    r"^(why|how come)\b.{0,40}\b(fail|failed|didn'?t work|did not work|error|wrong|stop|stopped)\b|"
    r"^what went wrong\b", re.I)
_BARE_PRONOUN = re.compile(r"^(do|send|open|run|repeat|try|close)?\s*(it|that|this|them|again)\s*[.!?]*$", re.I)
_COMPOUND = re.compile(r"\b(and\s+(then\s+)?|then\s+|after\s+(that|which)\s+|also\s+)\b", re.I)
_CONSEQUENTIAL_VERBS = re.compile(
    r"\b(send|email|mail|post|tweet|delete|remove|erase|submit|purchase|buy|pay|order|transfer|book|schedule|"
    r"publish|reply)\b", re.I)

# Deterministic information queries (zero-LLM) — ported from the existing engine.
_DETERMINISTIC: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(what time|current time|the time|tell me the time|check the time|clock|what date|"
                r"today'?s date|current date|what day is it)\b", re.I), "get_current_time"),
    (re.compile(r"\b(cpu usage|memory usage|ram usage|disk usage|disk space|storage space|battery|"
                r"system info|system information|sysinfo)\b", re.I), "get_system_info"),
    (re.compile(r"\b(screen size|display size|screen resolution)\b", re.I), "get_screen_size"),
    (re.compile(r"^(please\s+)?(take\s+(a\s+)?screenshot|capture\s+(the\s+)?screen|screenshot)(\s+please)?[.!]*$", re.I),
     "take_screenshot"),
]

# Generic single-action grammar: <verb> <name>. The name becomes the tool's primary argument.
_SINGLE_ACTION: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^(?:please\s+)?(?:open|launch|start)\s+(?P<name>[\w][\w .+\-]{0,40})$", re.I), "open_application"),
    (re.compile(r"^(?:please\s+)?(?:close|quit|exit)\s+(?P<name>[\w][\w .+\-]{0,40})$", re.I), "close_application"),
    (re.compile(r"^(?:please\s+)?(?:focus|switch\s+to)\s+(?P<name>[\w][\w .+\-]{0,40})$", re.I), "focus_application"),
]
_NOT_AN_APP = re.compile(
    r"^(a|an|the|my|this|that|it|new|file|folder|tab|page|website|site|url|timer|alarm|meeting|"
    r"call|task|game)\b|\b(file|folder|website|url|tab|page|http|www|\.com|\.org|\.net)\b", re.I)


@dataclass
class Intent:
    raw: str
    goal: str
    task_type: TaskType
    risk_level: str = "low"
    compound: bool = False
    fast_tool: Optional[str] = None
    fast_args: dict[str, Any] = field(default_factory=dict)
    feedback: Optional[Correction] = None
    classification_ms: float = 0.0


class IntentGateway:
    """Normalise and classify a raw request without invoking an LLM."""

    def __init__(self, registry: Any) -> None:
        self.registry = registry

    @staticmethod
    def normalize(raw: str) -> str:
        return tpl.normalize_request(raw)

    def classify(self, raw: str, has_history: bool = False) -> Intent:
        t0 = time.perf_counter()
        goal = self.normalize(raw)
        intent = self._classify(raw, goal, has_history)
        intent.classification_ms = (time.perf_counter() - t0) * 1000
        return intent

    def _classify(self, raw: str, goal: str, has_history: bool) -> Intent:
        low = goal.lower()
        compound = bool(_COMPOUND.search(low))

        fb = parse_feedback(raw)
        if fb is not None:
            return Intent(raw, goal, TaskType.FEEDBACK, feedback=fb)

        if _CONVERSATIONAL.match(low) or _ARITHMETIC.match(low):
            return Intent(raw, goal, TaskType.CONVERSATIONAL)

        if _RECOVERY_Q.search(low):
            return Intent(raw, goal, TaskType.RECOVERY)

        if _BARE_PRONOUN.match(low) and not has_history:
            return Intent(raw, goal, TaskType.AMBIGUOUS, compound=compound)

        if not compound:
            for pat, tool in _DETERMINISTIC:
                if pat.search(low) and self.registry.get(tool) is not None:
                    return Intent(raw, goal, TaskType.SIMPLE_DETERMINISTIC, fast_tool=tool)
            for pat, tool_name in _SINGLE_ACTION:
                m = pat.match(goal)
                if not m:
                    continue
                name = m.group("name").strip().strip(".!")
                tool = self.registry.get(tool_name)
                if tool is None or not name or _NOT_AN_APP.search(name) or len(name.split()) > 4:
                    break
                param = toolmeta.first_string_param(tool) or "application_name"
                return Intent(raw, goal, TaskType.SIMPLE_DETERMINISTIC, fast_tool=tool_name,
                              fast_args={param: name})

        if _CONSEQUENTIAL_VERBS.search(low):
            return Intent(raw, goal, TaskType.CONSEQUENTIAL_ACTION, risk_level="medium", compound=compound)
        if compound:
            return Intent(raw, goal, TaskType.MULTI_STEP, risk_level="low", compound=True)
        return Intent(raw, goal, TaskType.COMPLEX_REASONING, compound=compound)


class TaskRouter:
    """Selects the minimal relevant tool set for LLM reasoning (spec §33)."""

    def __init__(self, registry: Any) -> None:
        self.registry = registry

    def route(self, request: str, extra_tools: Optional[list[str]] = None) -> tuple[list[Any], list[str], float]:
        t0 = time.perf_counter()
        from harma.core.router import select_tools
        all_defs = self.registry.list_tool_definitions()
        try:
            selected, _tier, _total = select_tools(request, all_defs)
        except Exception:
            selected = list(all_defs)
        if not selected:
            selected = []
        names = {d.name for d in selected}
        for extra in extra_tools or []:
            if extra not in names:
                d = next((x for x in all_defs if x.name == extra), None)
                if d is not None:
                    selected.append(d)
                    names.add(extra)
        domains = sorted({toolmeta.domain_of(n) for n in names})
        return selected, domains, (time.perf_counter() - t0) * 1000
