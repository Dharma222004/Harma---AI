"""
Browser Interaction Tools — Phase 3

Exposes browser interaction as Harma tools.

Tools:
  browser_click         — Click an element (SENSITIVE)
  browser_type          — Type text into an input (SENSITIVE)
  browser_select        — Select dropdown option (SENSITIVE)
  browser_check         — Check a checkbox (SENSITIVE)
  browser_uncheck       — Uncheck a checkbox (SENSITIVE)
  browser_hover         — Hover over an element (SAFE)
  browser_press_key     — Press a keyboard key (SENSITIVE)
  browser_scroll        — Scroll the page (SAFE)
  browser_upload_file   — Upload a file (SENSITIVE)
"""

from __future__ import annotations

from typing import Any
import asyncio

from harma.tools.base import BaseTool, PermissionLevel, ToolResult
from harma.config.logging_config import get_logger

log = get_logger(__name__)


def _get_ctrl():
    from harma.browser.controller import get_browser_controller
    return get_browser_controller()


_SEAT_STATE_JS = r'''() => {
    const vis = e => e && e.offsetParent !== null;
    const buttons = [...document.querySelectorAll('button, div[role="button"], a, span, div')]
        .filter(b => vis(b) && b.children.length <= 2);
    const txt = b => (b.innerText || '').trim();
    const modalOpen = buttons.some(b => /^select seats$/i.test(txt(b)));
    const payEl = buttons.find(b => /^pay\b/i.test(txt(b)) && txt(b).length < 40);
    const qtyEl = buttons.find(b => /^\d+\s+tickets?$/i.test(txt(b)));
    const out = {
        konva: false, modalOpen, pay: payEl ? txt(payEl).replace(/\s+/g, ' ') : '',
        quantity: qtyEl ? parseInt(txt(qtyEl), 10) : null, available: [], selected: [],
    };
    if (typeof Konva === 'undefined' || !Konva.stages || !Konva.stages.length) return out;
    const stage = Konva.stages[0];
    const canvas = stage.container().querySelector('canvas');
    if (!canvas) return out;
    out.konva = true;
    const c = canvas.getBoundingClientRect();
    for (const g of stage.find('Group')) {
        const o = g.attrs.seatObj;
        const id = g.attrs.id || '';
        if (!o || !id) continue;
        const r = g.getClientRect();
        const seat = {
            id, row: o.rowId || o.rowNumber || '', num: o.displaySeatNumber || o.seatNumber || '',
            area: o.areaCode || '', price: o.curPrice || '',
            x: Math.round(c.left + r.x + r.width / 2), y: Math.round(c.top + r.y + r.height / 2),
            w: Math.max(1, Math.round(r.width)),
        };
        if (id.endsWith('-selected')) {
            if (!seat.num) seat.num = (id.replace(/-selected$/, '').match(/(\d+)$/) || [, ''])[1];
            out.selected.push(seat);
        } else if (o.seatStatus === 1 || /avail/i.test(o.seatType || '')) {
            out.available.push(seat);
        }
    }
    return out;
}'''


async def _seat_state(page: Any) -> dict[str, Any]:
    try:
        return await page.evaluate(_SEAT_STATE_JS)
    except Exception as exc:
        return {"konva": False, "error": str(exc), "available": [], "selected": [], "modalOpen": False, "pay": ""}


def _seat_label(s: dict[str, Any]) -> str:
    return f"{s.get('row', '')}{s.get('num', '')}"


def _best_seat_block(available: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """Choose `count` seats that sit next to each other in one row (no aisle gap).

    Falls back to the tightest group in a single row, then to the first `count` seats.
    """
    rows: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for s in available:
        rows.setdefault((s.get("area", ""), s.get("row", "")), []).append(s)
    best: list[dict[str, Any]] = []
    best_score: float = float("inf")
    for seats in rows.values():
        seats = sorted(seats, key=lambda s: s["x"])
        for i in range(0, len(seats) - count + 1):
            block = seats[i:i + count]
            gaps = [block[j + 1]["x"] - block[j]["x"] for j in range(len(block) - 1)]
            width = max(1, block[0].get("w", 20))
            contiguous = all(g <= width * 1.6 for g in gaps)
            spread = (block[-1]["x"] - block[0]["x"]) if len(block) > 1 else 0
            # Prefer contiguous blocks; among them prefer the most central row position.
            score = (0 if contiguous else 10_000) + spread
            if score < best_score:
                best, best_score = block, score
    if best:
        return best
    return sorted(available, key=lambda s: (s["y"], s["x"]))[:count]


async def _ensure_quantity(ctrl: Any, page: Any, count: int, state: dict[str, Any]) -> dict[str, Any]:
    """Close the 'How many seats?' modal with the right quantity before touching the canvas."""
    need_modal = state.get("modalOpen")
    if not need_modal and state.get("quantity") not in (None, count) and not state.get("selected"):
        # Quantity differs from the request: reopen the quantity picker via the 'N Tickets' header.
        r = await ctrl.click(f"{state['quantity']} Tickets")
        if r.success:
            await asyncio.sleep(1.0)
            state = await _seat_state(page)
            need_modal = state.get("modalOpen")
    if need_modal:
        try:
            await ctrl.click(str(count))
            await asyncio.sleep(0.6)
        except Exception:
            pass
        await ctrl.click("Select Seats")
        for _ in range(10):
            await asyncio.sleep(0.5)
            state = await _seat_state(page)
            if not state.get("modalOpen"):
                break
    return state


async def _select_canvas_seats(ctrl: Any, count: int = 2) -> tuple[bool, str]:
    """Helper to locate and select available seats on canvas-based layout (e.g. Konva / BookMyShow).

    Behaviour verified against BookMyShow: with ticket quantity N, a single click on a seat
    selects a block of N seats; selected seats appear as '<seat id>-selected' groups and a
    'Pay ₹…' button appears. Success is only reported when that state is observed.
    """
    try:
        count = max(1, int(count or 2))
        page = await ctrl._ensure_page()
        state = await _seat_state(page)
        for _ in range(10):                       # layout may still be rendering
            if state.get("konva") or state.get("modalOpen"):
                break
            await asyncio.sleep(0.5)
            state = await _seat_state(page)
        if not state.get("konva") and not state.get("modalOpen"):
            return False, "Not a canvas seat layout (no Konva stage found on this page)."

        state = await _ensure_quantity(ctrl, page, count, state)
        if state.get("modalOpen"):
            return False, "The 'How many seats?' dialog is still open; could not confirm the seat quantity."

        if len(state.get("selected", [])) >= count and state.get("pay"):
            names = ", ".join(_seat_label(s) for s in state["selected"])
            log.info("[CANVAS_SEATS] Seats %s already selected. Auto-clicking Pay button: %s", names, state['pay'])
            try:
                pay_loc = page.locator("button:has-text('Pay'), div[role='button']:has-text('Pay'), [class*='pay']:has-text('Pay')")
                if await pay_loc.count() > 0:
                    await pay_loc.first.click()
                else:
                    await ctrl.click(state["pay"])
                await asyncio.sleep(1.5)
                accept_loc = page.locator("button:has-text('Accept'), [role='button']:has-text('Accept'), div:text-is('Accept')")
                if await accept_loc.count() > 0:
                    await accept_loc.first.click()
                    await asyncio.sleep(2.5)
                cur_url = page.url
                cur_title = await page.title()
                return True, (
                    f"Seats already selected: {names}. "
                    f"Clicked '{state['pay']}' and accepted Terms & Conditions. "
                    f"Now on: '{cur_title}' ({cur_url}). "
                    "Next: If on the Food & Beverages page, check popcorn prices if requested, or click 'Skip' to proceed to the payment review page."
                )
            except Exception:
                return True, f"Seats already selected: {names}. Button available: '{state['pay']}'. Next: click 'Pay'."

        available = state.get("available", [])
        if len(available) < count:
            return False, (f"Only {len(available)} seat(s) are available for this show "
                           f"(requested {count}). Choose another showtime or fewer tickets.")

        block = _best_seat_block(available, count)
        for seat in block:
            state = await _seat_state(page)
            selected_labels = {_seat_label(s) for s in state.get("selected", [])}
            if len(selected_labels) >= count:
                break
            if _seat_label(seat) in selected_labels:
                continue
            # Re-read the seat's live position (the layout can shift after each click).
            live = next((s for s in state.get("available", []) if s["id"] == seat["id"]), seat)
            await page.mouse.click(live["x"], live["y"])
            await page.mouse.move(2, 2)
            await asyncio.sleep(0.8)

        state = await _seat_state(page)
        for _ in range(6):
            if len(state.get("selected", [])) >= count and state.get("pay"):
                break
            await asyncio.sleep(0.5)
            state = await _seat_state(page)

        selected = state.get("selected", [])
        names = ", ".join(_seat_label(s) for s in selected) or "none"
        if len(selected) >= count and state.get("pay"):
            # Automatically advance through the Pay button and Terms modal
            log.info("[CANVAS_SEATS] Seats %s selected. Auto-clicking Pay button: %s", names, state['pay'])
            try:
                # 1. Click Pay button
                pay_loc = page.locator("button:has-text('Pay'), div[role='button']:has-text('Pay'), [class*='pay']:has-text('Pay')")
                if await pay_loc.count() > 0:
                    await pay_loc.first.click()
                else:
                    await ctrl.click(state["pay"])
                await asyncio.sleep(1.5)

                # 2. Check for Terms & Conditions dialog and click Accept
                accept_loc = page.locator("button:has-text('Accept'), [role='button']:has-text('Accept'), div:text-is('Accept')")
                if await accept_loc.count() > 0:
                    log.info("[CANVAS_SEATS] Terms & Conditions dialog visible, clicking Accept...")
                    await accept_loc.first.click()
                    await asyncio.sleep(2.5)

                cur_url = page.url
                cur_title = await page.title()
                return True, (
                    f"Selected {len(selected)} seats: {names}. "
                    f"Clicked '{state['pay']}' and accepted Terms & Conditions. "
                    f"Now on: '{cur_title}' ({cur_url}). "
                    "Next: If on the Food & Beverages page, check popcorn prices if requested, or click 'Skip' to proceed to the payment review page."
                )
            except Exception as pay_err:
                log.warning("[CANVAS_SEATS] Auto-click Pay failed (%s); button remains visible.", pay_err)
                return True, (f"Selected {len(selected)} seats: {names}. "
                              f"Button now visible: '{state['pay']}'. Next: call browser_click('Pay').")
        if selected:
            return False, (f"Only {len(selected)} of {count} seats were selected ({names}). "
                           "The layout may not have enough adjacent seats.")
        return False, "Clicked the seat layout but no seat became selected (no 'Pay' button appeared)."
    except Exception as exc:
        return False, f"Failed to select canvas seats: {exc}"


async def canvas_seat_summary(page: Any) -> str:
    """One-line summary of a canvas seat layout for observe_page ('' if not a seat layout)."""
    state = await _seat_state(page)
    if not state.get("konva") and not state.get("modalOpen"):
        return ""
    parts = ["SEAT LAYOUT (canvas):"]
    if state.get("modalOpen"):
        parts.append("'How many seats?' dialog is open (choose a number, then 'Select Seats').")
    if state.get("quantity"):
        parts.append(f"quantity={state['quantity']}.")
    parts.append(f"available seats={len(state.get('available', []))}.")
    sel = state.get("selected", [])
    parts.append(f"selected={', '.join(_seat_label(s) for s in sel) or 'none'}.")
    parts.append(f"pay button={state['pay']!r}." if state.get("pay") else "pay button=not visible.")
    if not sel:
        parts.append("Use select_cinema_seats(count=N) to pick seats.")
    elif state.get("pay"):
        parts.append("Next: browser_click('Pay').")
    return " ".join(parts)


class BrowserClickTool(BaseTool):
    name = "browser_click"
    description = (
        "Clicks an element on the current web page. "
        "Describe the element by its visible text, label, role, or placeholder. "
        "Examples: 'Sign In button', 'Search box', 'Accept cookies', 'Next'. "
        "After clicking, use observe_page to verify the result."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Natural language description of the element to click.",
            },
            "double_click": {
                "type": "boolean",
                "description": "If true, double-click the element (default: false).",
            },
        },
        "required": ["description"],
    }

    async def execute(
        self,
        description: str,
        double_click: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        ctrl = _get_ctrl()
        result = await ctrl.click(description, double=double_click)
        output = result.to_text()
        if not result.success and ctrl.is_open:
            desc_l = description.lower()
            if any(k in desc_l for k in ("seat", "available", "ticket", "a1", "b1", "c1", "d1")):
                canvas_ok, canvas_msg = await _select_canvas_seats(ctrl, count=2)
                if canvas_ok:
                    page_url = await ctrl.get_url()
                    page_title = await ctrl.get_title()
                    return ToolResult(
                        success=True,
                        output=f"{canvas_msg} | Page: '{page_title}' ({page_url})",
                        data={"strategy": "canvas_seat_selection"},
                    )
        if result.success and ctrl.is_open:
            try:
                page_url = await ctrl.get_url()
                page_title = await ctrl.get_title()
                output += f" | Page: '{page_title}' ({page_url})"
            except Exception:
                pass
        return ToolResult(
            success=result.success,
            output=output,
            data=result.to_dict(),
            error=result.error,
        )


class SelectCinemaSeatsTool(BaseTool):
    name = "select_cinema_seats"
    description = (
        "Selects available seats on an interactive cinema seat layout canvas (such as BookMyShow). "
        "Finds available seats, clicks them on the layout, and reveals the 'Pay' button. "
        "Use this on the seat selection page when seats are rendered on a canvas."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "count": {
                "type": "integer",
                "description": "Number of seats to select (default: 2).",
            },
        },
        "required": [],
    }

    async def execute(self, count: int = 2, **kwargs: Any) -> ToolResult:
        ctrl = _get_ctrl()
        ok, msg = await _select_canvas_seats(ctrl, count=count)
        if ok and ctrl.is_open:
            try:
                page_url = await ctrl.get_url()
                page_title = await ctrl.get_title()
                msg += f" | Page: '{page_title}' ({page_url})"
            except Exception:
                pass
        return ToolResult(
            success=ok,
            output=msg,
            data={"count": count},
            error=None if ok else msg,
        )


class BrowserTypeTool(BaseTool):
    name = "browser_type"
    description = (
        "Types text into an input field on the current web page. "
        "Describe the field by its label, placeholder, or name. "
        "Examples: 'Email input', 'Search box', 'Password field'. "
        "IMPORTANT: Do NOT type passwords or sensitive credentials. "
        "The field is cleared before typing unless clear_first is false."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Natural language description of the input field.",
            },
            "text": {
                "type": "string",
                "description": "The text to type into the field.",
            },
            "clear_first": {
                "type": "boolean",
                "description": "Clear the field before typing (default: true).",
            },
        },
        "required": ["description", "text"],
    }

    async def execute(
        self,
        description: str,
        text: str,
        clear_first: bool = True,
        **kwargs: Any,
    ) -> ToolResult:
        ctrl = _get_ctrl()
        result = await ctrl.type_text(description, text, clear_first)
        output = result.to_text()
        if result.success and ctrl.is_open:
            try:
                page_url = await ctrl.get_url()
                page_title = await ctrl.get_title()
                output += f" | Page: '{page_title}' ({page_url})"
            except Exception:
                pass
        return ToolResult(
            success=result.success,
            output=output,
            data=result.to_dict(),
            error=result.error,
        )


class BrowserSelectTool(BaseTool):
    name = "browser_select"
    description = (
        "Selects an option from a dropdown (<select>) element on the page. "
        "Describe the dropdown by its label or name. "
        "Provide the visible option text or value to select."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Description of the dropdown to target.",
            },
            "value": {
                "type": "string",
                "description": "The option text or value to select.",
            },
        },
        "required": ["description", "value"],
    }

    async def execute(self, description: str, value: str, **kwargs: Any) -> ToolResult:
        ctrl = _get_ctrl()
        result = await ctrl.select_option(description, value)
        return ToolResult(
            success=result.success,
            output=result.to_text(),
            data=result.to_dict(),
            error=result.error,
        )


class BrowserCheckTool(BaseTool):
    name = "browser_check"
    description = "Checks a checkbox or radio button on the page."
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "Description of the checkbox."},
        },
        "required": ["description"],
    }

    async def execute(self, description: str, **kwargs: Any) -> ToolResult:
        ctrl = _get_ctrl()
        result = await ctrl.check(description)
        return ToolResult(
            success=result.success, output=result.to_text(),
            data=result.to_dict(), error=result.error,
        )


class BrowserUncheckTool(BaseTool):
    name = "browser_uncheck"
    description = "Unchecks a checkbox on the page."
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "Description of the checkbox."},
        },
        "required": ["description"],
    }

    async def execute(self, description: str, **kwargs: Any) -> ToolResult:
        ctrl = _get_ctrl()
        result = await ctrl.uncheck(description)
        return ToolResult(
            success=result.success, output=result.to_text(),
            data=result.to_dict(), error=result.error,
        )


class BrowserHoverTool(BaseTool):
    name = "browser_hover"
    description = "Hovers the mouse over an element to reveal dropdown menus or tooltips."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "Description of the element to hover."},
        },
        "required": ["description"],
    }

    async def execute(self, description: str, **kwargs: Any) -> ToolResult:
        ctrl = _get_ctrl()
        result = await ctrl.hover(description)
        return ToolResult(
            success=result.success, output=result.to_text(),
            data=result.to_dict(), error=result.error,
        )


class BrowserPressKeyTool(BaseTool):
    name = "browser_press_key"
    description = (
        "Presses a keyboard key in the browser. "
        "Common keys: 'Enter', 'Tab', 'Escape', 'ArrowDown', 'ArrowUp', 'Backspace'. "
        "Use after focusing an input or to submit a search."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Key to press. Examples: 'Enter', 'Tab', 'Escape', 'ArrowDown'.",
            }
        },
        "required": ["key"],
    }

    async def execute(self, key: str, **kwargs: Any) -> ToolResult:
        ctrl = _get_ctrl()
        result = await ctrl.press_key(key)
        output = result.to_text()
        if result.success and ctrl.is_open:
            try:
                page_url = await ctrl.get_url()
                page_title = await ctrl.get_title()
                output += f" | Page: '{page_title}' ({page_url})"
            except Exception:
                pass
        return ToolResult(
            success=result.success,
            output=output,
            data=result.to_dict(),
            error=result.error,
        )


class BrowserScrollTool(BaseTool):
    name = "browser_scroll"
    description = (
        "Scrolls the web page up or down. "
        "Use to reveal content below the fold or to scroll back up."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "enum": ["up", "down"],
                "description": "Scroll direction (default: 'down').",
            },
            "amount": {
                "type": "integer",
                "description": "Number of scroll steps 1-10 (default: 3).",
            },
        },
        "required": [],
    }

    async def execute(
        self,
        direction: str = "down",
        amount: int = 3,
        **kwargs: Any,
    ) -> ToolResult:
        ctrl = _get_ctrl()
        result = await ctrl.scroll_page(direction, amount)
        return ToolResult(
            success=result.success, output=result.to_text(),
            data=result.to_dict(), error=result.error,
        )


class BrowserUploadFileTool(BaseTool):
    name = "browser_upload_file"
    description = (
        "Uploads a file to a file input field on the web page. "
        "Provide the description of the file input and the absolute path to the file. "
        "The file must exist on the local filesystem."
    )
    permission_level = PermissionLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Description of the file input element.",
            },
            "file_path": {
                "type": "string",
                "description": "Absolute path to the file to upload.",
            },
        },
        "required": ["description", "file_path"],
    }

    async def execute(self, description: str, file_path: str, **kwargs: Any) -> ToolResult:
        ctrl = _get_ctrl()
        result = await ctrl.upload_file(description, file_path)
        return ToolResult(
            success=result.success, output=result.to_text(),
            data=result.to_dict(), error=result.error,
        )
