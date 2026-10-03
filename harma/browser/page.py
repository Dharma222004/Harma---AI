"""
Harma Browser Page Observation

Converts a live Playwright page into structured, LLM-friendly observations.

The key design principle:
  Raw HTML → structured observation → LLM
  NOT: raw HTML → LLM (wasteful and slow)

PageObservation provides:
  - URL and title
  - Visible text (cleaned)
  - Interactive elements: buttons, inputs, links, selects
  - Forms and their fields
  - Headings (for page structure)
  - Tables (first 5 rows)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from harma.config.logging_config import get_logger

if TYPE_CHECKING:
    from playwright.async_api import Page

log = get_logger(__name__)

# Limit text extraction to avoid sending huge pages to the LLM
_MAX_TEXT_CHARS = 4000
_MAX_ELEMENTS = 30
_MAX_LINKS = 20
_MAX_TABLE_ROWS = 5


@dataclass
class ElementInfo:
    """A single interactive element on the page."""
    tag: str              # button, input, a, select, textarea
    role: str = ""        # ARIA role
    text: str = ""        # visible text or label
    name: str = ""        # name attribute
    placeholder: str = "" # placeholder text
    href: str = ""        # for links
    element_type: str = "" # for inputs (text, checkbox, etc.)
    selector: str = ""    # best CSS selector for this element
    is_visible: bool = True

    def describe(self) -> str:
        parts = [f"<{self.tag}>"]
        if self.text:
            parts.append(f"text={self.text!r}")
        if self.placeholder:
            parts.append(f"placeholder={self.placeholder!r}")
        if self.name:
            parts.append(f"name={self.name!r}")
        if self.role:
            parts.append(f"role={self.role!r}")
        if self.href:
            parts.append(f"href={self.href!r}")
        return " ".join(parts)


@dataclass
class FormInfo:
    """A web form and its fields."""
    action: str = ""
    method: str = "GET"
    fields: List[ElementInfo] = field(default_factory=list)


@dataclass
class PageObservation:
    """
    Structured view of a browser page.

    Used by the agent's OBSERVE step for browser tasks.
    """
    url: str = ""
    title: str = ""
    visible_text: str = ""
    headings: List[str] = field(default_factory=list)
    buttons: List[ElementInfo] = field(default_factory=list)
    inputs: List[ElementInfo] = field(default_factory=list)
    links: List[ElementInfo] = field(default_factory=list)
    selects: List[ElementInfo] = field(default_factory=list)
    forms: List[FormInfo] = field(default_factory=list)
    tables: List[List[str]] = field(default_factory=list)
    alert_text: str = ""
    error: str = ""

    def to_text(self) -> str:
        """Compact text summary for the LLM."""
        lines = [
            f"URL: {self.url}",
            f"Title: {self.title}",
        ]
        if self.headings:
            lines.append("Headings: " + " | ".join(self.headings[:5]))
        if self.buttons:
            btn_list = [e.text or e.name or "(unlabelled)" for e in self.buttons[:10]]
            lines.append("Buttons: " + ", ".join(btn_list))
        if self.inputs:
            inp_list = [e.placeholder or e.name or e.element_type or "input" for e in self.inputs[:10]]
            lines.append("Inputs: " + ", ".join(inp_list))
        if self.links:
            link_list = [e.text or e.href for e in self.links[:8]]
            lines.append("Links: " + ", ".join(link_list))
        if self.selects:
            sel_list = [e.name or e.text or "select" for e in self.selects[:5]]
            lines.append("Dropdowns: " + ", ".join(sel_list))
        if self.forms:
            lines.append(f"Forms: {len(self.forms)} form(s) detected")
        if self.alert_text:
            lines.append(f"Alert: {self.alert_text}")
        if self.visible_text:
            lines.append("\n--- Page text (excerpt) ---")
            lines.append(self.visible_text[:_MAX_TEXT_CHARS])
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "headings": self.headings,
            "buttons": [e.__dict__ for e in self.buttons],
            "inputs": [e.__dict__ for e in self.inputs],
            "links": [e.__dict__ for e in self.links[:_MAX_LINKS]],
            "selects": [e.__dict__ for e in self.selects],
            "forms": len(self.forms),
            "visible_text_length": len(self.visible_text),
        }


async def observe_page(page: "Page") -> PageObservation:
    """
    Observe the current state of a Playwright page.

    Extracts structured data: URL, title, text, interactive elements.
    Never sends raw HTML to the caller — only cleaned, structured content.
    """
    obs = PageObservation()
    try:
        obs.url = page.url
        obs.title = await page.title()
        log.info("[PAGE] Observing: %s | %s", obs.url, obs.title)

        # ── Visible text ──────────────────────────────────────────────────────
        try:
            raw_text = await page.evaluate("""() => {
                const walker = document.createTreeWalker(
                    document.body,
                    NodeFilter.SHOW_TEXT,
                    {
                        acceptNode: function(node) {
                            const style = window.getComputedStyle(node.parentElement);
                            if (style.display === 'none' || style.visibility === 'hidden')
                                return NodeFilter.FILTER_REJECT;
                            return NodeFilter.FILTER_ACCEPT;
                        }
                    }
                );
                const texts = [];
                let node;
                while (node = walker.nextNode()) {
                    const t = node.textContent.trim();
                    if (t.length > 1) texts.push(t);
                }
                return texts.join(' ');
            }""")
            # Clean up excessive whitespace
            obs.visible_text = re.sub(r"\s+", " ", raw_text).strip()[:_MAX_TEXT_CHARS * 2]
        except Exception as e:
            log.debug("[PAGE] Text extraction failed: %s", e)

        # ── Headings ──────────────────────────────────────────────────────────
        try:
            headings_raw = await page.evaluate("""() =>
                Array.from(document.querySelectorAll('h1,h2,h3'))
                     .map(h => h.innerText.trim())
                     .filter(t => t.length > 0)
                     .slice(0, 10)
            """)
            obs.headings = headings_raw or []
        except Exception:
            pass

        # ── Buttons ───────────────────────────────────────────────────────────
        try:
            btns = await page.evaluate("""() =>
                Array.from(document.querySelectorAll('button,[role="button"],input[type="submit"],input[type="button"]'))
                     .filter(el => el.offsetParent !== null)
                     .slice(0, 30)
                     .map(el => ({
                         tag: el.tagName.toLowerCase(),
                         text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0,80),
                         name: el.name || '',
                         role: el.getAttribute('role') || '',
                     }))
            """)
            obs.buttons = [
                ElementInfo(tag=b["tag"], text=b["text"], name=b["name"], role=b["role"])
                for b in (btns or [])
                if b.get("text") or b.get("name")
            ][:_MAX_ELEMENTS]
        except Exception:
            pass

        # ── Inputs ────────────────────────────────────────────────────────────
        try:
            inputs_raw = await page.evaluate("""() =>
                Array.from(document.querySelectorAll('input:not([type="hidden"]),textarea'))
                     .filter(el => el.offsetParent !== null)
                     .slice(0, 20)
                     .map(el => ({
                         tag: el.tagName.toLowerCase(),
                         element_type: el.type || 'text',
                         placeholder: (el.placeholder || '').trim().slice(0,80),
                         name: el.name || el.id || '',
                         role: el.getAttribute('role') || '',
                         value: (el.value || '').slice(0,40),
                     }))
            """)
            obs.inputs = [
                ElementInfo(
                    tag=i["tag"],
                    element_type=i["element_type"],
                    placeholder=i["placeholder"],
                    name=i["name"],
                    role=i["role"],
                )
                for i in (inputs_raw or [])
            ]
        except Exception:
            pass

        # ── Links ─────────────────────────────────────────────────────────────
        try:
            links_raw = await page.evaluate("""() =>
                Array.from(document.querySelectorAll('a[href]'))
                     .filter(el => el.offsetParent !== null && el.innerText.trim().length > 0)
                     .slice(0, 25)
                     .map(el => ({
                         text: el.innerText.trim().slice(0,80),
                         href: el.href || '',
                     }))
            """)
            obs.links = [
                ElementInfo(tag="a", text=lk["text"], href=lk["href"])
                for lk in (links_raw or [])
            ]
        except Exception:
            pass

        # ── Selects ───────────────────────────────────────────────────────────
        try:
            sels_raw = await page.evaluate("""() =>
                Array.from(document.querySelectorAll('select'))
                     .filter(el => el.offsetParent !== null)
                     .slice(0, 10)
                     .map(el => ({
                         name: el.name || el.id || '',
                         text: (el.getAttribute('aria-label') || '').trim(),
                     }))
            """)
            obs.selects = [
                ElementInfo(tag="select", name=s["name"], text=s["text"])
                for s in (sels_raw or [])
            ]
        except Exception:
            pass

        # ── Tables ────────────────────────────────────────────────────────────
        try:
            tables_raw = await page.evaluate(f"""() => {{
                const tables = [];
                document.querySelectorAll('table').forEach(tbl => {{
                    const rows = [];
                    tbl.querySelectorAll('tr').forEach((tr, ri) => {{
                        if (ri > {_MAX_TABLE_ROWS}) return;
                        const cells = Array.from(tr.querySelectorAll('td,th'))
                                          .map(c => c.innerText.trim().slice(0,50));
                        if (cells.length) rows.push(cells);
                    }});
                    if (rows.length) tables.push(rows);
                }});
                return tables.slice(0, 3);
            }}""")
            obs.tables = tables_raw or []
        except Exception:
            pass

    except Exception as exc:
        obs.error = str(exc)
        log.error("[PAGE] Observation failed: %s", exc)

    return obs
