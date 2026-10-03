"""
Harma Runtime V3 — Generic Task Parameterisation

Turns a verified (request, steps) pair into a reusable, slot-parameterised procedure
WITHOUT any application- or keyword-specific rules:

    request : Open Notepad and type "hello"
    steps   : open_application(application_name="Notepad"), type_text(text="hello")
    template: open {s0} and type "{s1}"
    steps'  : open_application(application_name="{s0}"), type_text(text="{s1}")

A slot is created only when a phrase of the user's request is (the substantial part of)
an argument value the runtime actually executed. Structure, not keywords, drives learning.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional
from urllib.parse import parse_qsl, quote_plus, unquote_plus, urlsplit

STOPWORDS = frozenset({
    "a", "an", "the", "to", "for", "of", "in", "on", "at", "and", "or", "then", "please",
    "me", "my", "it", "is", "be", "with", "from", "by", "up", "can", "you", "could", "would",
    "now", "also", "this", "that", "some", "i", "want", "need", "harma",
})

_EDGE_PUNCT = "\"'`“”‘’.,!?;:()[]{}"
_SLOT_RE = re.compile(r"\{(s\d+)(\|url)?\}")


def normalize_request(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    return t.rstrip(".!?;").strip()


def content_tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 1}


def _clean(word: str) -> str:
    return word.strip(_EDGE_PUNCT)


def _value_targets(value: str) -> list[tuple[str, bool]]:
    """Return candidate (text, is_url_component) targets inside an argument value."""
    v = value.strip()
    if re.match(r"^https?://", v, re.I):
        parts = urlsplit(v)
        # Only query values are user-supplied data; path segments are site structure
        # (e.g. "/search") and must never become slots.
        return [(unquote_plus(qv), True) for _, qv in parse_qsl(parts.query) if qv]
    return [(v, False)]


def _phrase_matches(phrase: str, target: str) -> bool:
    p, t = phrase.lower(), target.lower().strip().strip(_EDGE_PUNCT)
    if not p or not t:
        return False
    if p == t:
        return True
    return p in t and len(p) >= 0.5 * len(t)


def build_template(request: str, steps: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """
    Parameterise a request/steps pair.

    Returns dict(template, slots, steps, bindings) or None when no safe template exists.
    """
    norm = normalize_request(request)
    raw_words = norm.split(" ")
    words = [_clean(w) for w in raw_words]
    n_words = len(words)

    # 1. Collect matches: (span_len, start, end, phrase)
    string_values: list[str] = []
    for st in steps:
        for v in (st.get("arguments") or {}).values():
            if isinstance(v, str) and v.strip():
                string_values.append(v)

    _quotes = "\"'`“”‘’"
    candidates: list[tuple[int, int, int, str]] = []
    for size in range(min(8, n_words), 0, -1):
        for i in range(0, n_words - size + 1):
            span = words[i:i + size]
            if not all(span):
                continue
            phrase = " ".join(span)
            first, last = raw_words[i], raw_words[i + size - 1].rstrip(".,!?;:")
            quoted = first[:1] in _quotes and last[-1:] in _quotes   # explicit user-supplied data
            if not quoted and (all(w.lower() in STOPWORDS for w in span) or len(phrase) < 2):
                continue
            for v in string_values:
                if not quoted and len(v.strip()) < 2:
                    continue
                if any(_phrase_matches(phrase, tgt) for tgt, _ in _value_targets(v)):
                    candidates.append((size, i, i + size, phrase))
                    break

    # 2. Greedy non-overlapping selection, longest first
    chosen: list[tuple[int, int, str]] = []
    used = [False] * n_words
    for size, s, e, phrase in sorted(candidates, key=lambda c: (-c[0], c[1])):
        if any(used[s:e]):
            continue
        chosen.append((s, e, phrase))
        for k in range(s, e):
            used[k] = True
    if not chosen:
        return None
    chosen.sort()

    # A safe template must keep at least one literal, non-stopword token
    literal = [words[k] for k in range(n_words) if not used[k]]
    if not any(w and w.lower() not in STOPWORDS for w in literal):
        return None

    slots: list[str] = []
    bindings: dict[str, str] = {}
    phrase_to_slot: dict[str, str] = {}
    for s, e, phrase in chosen:
        key = phrase.lower()
        if key not in phrase_to_slot:
            name = f"s{len(phrase_to_slot)}"
            phrase_to_slot[key] = name
            slots.append(name)
            bindings[name] = phrase

    # 3. Build template string preserving surrounding punctuation of the slotted span
    out: list[str] = []
    k = 0
    starts = {s: (e, phrase) for s, e, phrase in chosen}
    while k < n_words:
        if k in starts:
            e, phrase = starts[k]
            first, last = raw_words[k], raw_words[e - 1]
            lead = first[: len(first) - len(first.lstrip(_EDGE_PUNCT))]
            trail = last[len(last.rstrip(_EDGE_PUNCT)):]
            out.append(f"{lead}{{{phrase_to_slot[phrase.lower()]}}}{trail}")
            k = e
        else:
            out.append(raw_words[k].lower())
            k += 1
    template = " ".join(out)

    # Adjacent slots ("{s0} {s1}") cannot be split unambiguously — refuse to learn them.
    if re.search(r"\{s\d+\}[\"'`]?\s+[\"'`]?\{s\d+\}", template):
        return None

    # 4. Parameterise step arguments
    param_steps: list[dict[str, Any]] = []
    for st in steps:
        new_args: dict[str, Any] = {}
        for ak, av in (st.get("arguments") or {}).items():
            new_args[ak] = _parameterise_value(av, phrase_to_slot) if isinstance(av, str) else av
        param_steps.append({"tool": st["tool"], "arguments": new_args})

    # Round-trip safety check: re-instantiating must reproduce exactly what was executed.
    original = [{"tool": s["tool"], "arguments": dict(s.get("arguments") or {})} for s in steps]
    rebuilt = instantiate_steps(param_steps, bindings)
    if json.dumps(rebuilt, sort_keys=True, default=str).lower() != json.dumps(original, sort_keys=True, default=str).lower():
        return None

    return {"template": template, "slots": slots, "steps": param_steps, "bindings": bindings}


def _parameterise_value(value: str, phrase_to_slot: dict[str, str]) -> str:
    out = value
    for phrase, slot in sorted(phrase_to_slot.items(), key=lambda kv: -len(kv[0])):
        if len(phrase) <= 2:
            # Very short phrases only ever bind a whole argument value.
            if out.strip().lower() == phrase.lower():
                out = f"{{{slot}}}"
            continue
        enc = quote_plus(phrase)
        if re.match(r"^https?://", out, re.I):
            out = re.sub(r"(?<![\w%])" + re.escape(enc) + r"(?![\w%])", f"{{{slot}|url}}", out, flags=re.I)
            out = re.sub(r"(?<![\w%])" + re.escape(phrase.replace(" ", "%20")) + r"(?![\w%])", f"{{{slot}|url}}", out, flags=re.I)
        out = re.sub(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", f"{{{slot}}}", out, flags=re.I)
    return out


def template_regex(template: str) -> re.Pattern:
    parts = _SLOT_RE.split(template)
    # split yields: literal, slot, urlflag, literal, slot, urlflag, ...
    pattern = "^"
    i = 0
    seen: set[str] = set()
    while i < len(parts):
        lit = parts[i]
        pattern += r"\s+".join(re.escape(x) for x in lit.split(" ")) if lit else ""
        if i + 1 < len(parts):
            slot = parts[i + 1]
            pattern += f"(?P={slot})" if slot in seen else f"(?P<{slot}>.+?)"
            seen.add(slot)
        i += 3
    pattern += "$"
    return re.compile(pattern, re.I)


def match_template(template: str, request: str) -> Optional[dict[str, str]]:
    """Return slot bindings if the request is an instance of the template."""
    m = template_regex(template).match(normalize_request(request))
    if not m:
        return None
    binds = {k: _clean(v.strip()) for k, v in m.groupdict().items()}
    if any(not v for v in binds.values()):
        return None
    return binds


def instantiate_steps(param_steps: list[dict[str, Any]], bindings: dict[str, str]) -> list[dict[str, Any]]:
    def fill(v: Any) -> Any:
        if not isinstance(v, str):
            return v
        return _SLOT_RE.sub(
            lambda m: quote_plus(bindings.get(m.group(1), "")) if m.group(2) else bindings.get(m.group(1), ""),
            v,
        )
    return [{"tool": s["tool"], "arguments": {k: fill(v) for k, v in s.get("arguments", {}).items()}} for s in param_steps]


def task_pattern(steps: list[dict[str, Any]]) -> str:
    return ">".join(s["tool"] for s in steps)


def procedure_key(param_steps: list[dict[str, Any]]) -> str:
    canon = json.dumps(param_steps, sort_keys=True, default=str)
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:16]


def similarity(request: str, template: str) -> float:
    """Token-structure similarity between a request and a template's literal tokens (0..1)."""
    literal = _SLOT_RE.sub(" ", template)
    a, b = content_tokens(request), content_tokens(literal)
    if not a or not b:
        return 0.0
    overlap = len(a & b)
    # Blend containment (template literals present in request) with Jaccard.
    return 0.6 * (overlap / len(b)) + 0.4 * (overlap / len(a | b))
