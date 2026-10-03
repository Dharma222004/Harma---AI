"""
Harma Keyboard Module

Low-level keyboard input.
All operations pass through safety validation.

Supported operations:
  type_text(text)         — Type a string character by character
  press_key(key)          — Press a single key (e.g. 'enter', 'f5')
  hotkey(keys)            — Press a key combination (e.g. ['ctrl', 'c'])

Key names follow pyautogui's conventions (lowercase):
  enter, tab, space, backspace, delete, escape, esc
  ctrl, alt, shift, win (Windows key)
  f1..f12
  up, down, left, right
  home, end, pageup, pagedown
  a..z, 0..9
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List

from harma.computer.safety import SafetyError, enforce_rate_limit, validate_text, validate_key
from harma.config.logging_config import get_logger

log = get_logger(__name__)

# Canonical key-name aliases  (user-facing → pyautogui)
_KEY_ALIASES: dict[str, str] = {
    "enter": "enter",
    "return": "enter",
    "tab": "tab",
    "space": "space",
    "backspace": "backspace",
    "delete": "delete",
    "del": "delete",
    "escape": "escape",
    "esc": "escape",
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "win": "win",
    "windows": "win",
    "cmd": "command",   # macOS
    "command": "command",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "home": "home",
    "end": "end",
    "pageup": "pageup",
    "pagedown": "pagedown",
    "insert": "insert",
    "printscreen": "printscreen",
    "prtsc": "printscreen",
    "capslock": "capslock",
    "numlock": "numlock",
    "scrolllock": "scrolllock",
    **{f"f{i}": f"f{i}" for i in range(1, 13)},   # f1..f12
    **{str(i): str(i) for i in range(10)},          # 0..9
    **{c: c for c in "abcdefghijklmnopqrstuvwxyz"},  # a..z
}


@dataclass
class KeyboardResult:
    """Result of a keyboard operation."""
    success: bool
    action: str
    detail: str = ""
    error: str = ""

    def to_text(self) -> str:
        if self.success:
            return f"{self.action}: {self.detail}"
        return f"{self.action} failed: {self.error}"

    def to_dict(self) -> dict:
        d = {"success": self.success, "action": self.action, "detail": self.detail}
        if not self.success:
            d["error"] = self.error
        return d


def _get_pyautogui():
    try:
        import pyautogui
        pyautogui.FAILSAFE = True
        return pyautogui
    except ImportError:
        raise SafetyError(
            "pyautogui is required for keyboard control. "
            "Install with: pip install pyautogui"
        )


def _resolve_key(key: str) -> str:
    """Normalise a key name to pyautogui's expected format."""
    k = key.strip().lower()
    return _KEY_ALIASES.get(k, k)


def type_text(text: str, interval: float = 0.03) -> KeyboardResult:
    """
    Type a string of text.

    Args:
        text: The text to type.
        interval: Delay between keystrokes in seconds (default 30ms).
                  Slower = more reliable in some apps.
    """
    # Sanitise — do NOT log actual content (could be passwords)
    log.info("[KEYBOARD] type_text  length=%d chars", len(text))
    try:
        enforce_rate_limit()
        cleaned = validate_text(text)
        pag = _get_pyautogui()
        try:
            pag.typewrite(cleaned, interval=interval)
            time.sleep(0.05)
        except Exception as write_err:
            log.warning("[KEYBOARD] typewrite failed (%s), falling back to clipboard paste", write_err)
            return type_text_clipboard(cleaned)
        return KeyboardResult(
            success=True,
            action="type_text",
            detail=f"Typed {len(cleaned)} characters",
        )
    except SafetyError as e:
        return KeyboardResult(success=False, action="type_text", error=str(e))
    except Exception as exc:
        err = f"Type text failed: {exc}"
        log.error("[KEYBOARD] %s", err)
        return KeyboardResult(success=False, action="type_text", error=err)


def type_text_clipboard(text: str) -> KeyboardResult:
    """
    Type text via clipboard paste — handles special characters pyautogui can't type.

    Uses pyperclip + Ctrl+V to paste. More reliable for Unicode/special chars.

    Args:
        text: The text to type.
    """
    log.info("[KEYBOARD] type_text_clipboard  length=%d chars", len(text))
    try:
        enforce_rate_limit()
        cleaned = validate_text(text)
        import pyperclip
        pyperclip.copy(cleaned)
        pag = _get_pyautogui()
        pag.hotkey("ctrl", "v")
        time.sleep(0.05)
        return KeyboardResult(
            success=True,
            action="type_text_clipboard",
            detail=f"Pasted {len(cleaned)} characters via clipboard",
        )
    except ImportError:
        # Fall back to typewrite
        log.debug("[KEYBOARD] pyperclip not available, using typewrite fallback")
        return type_text(text)
    except SafetyError as e:
        return KeyboardResult(success=False, action="type_text_clipboard", error=str(e))
    except Exception as exc:
        err = f"Clipboard type failed: {exc}"
        log.error("[KEYBOARD] %s", err)
        return KeyboardResult(success=False, action="type_text_clipboard", error=err)


def _normalize_keys(keys: Any) -> List[str]:
    """Safely normalize key combinations from various formats (list, json string, plus-delimited)."""
    if isinstance(keys, str):
        s = keys.strip()
        # Handle JSON or Python array string e.g. '["ctrl", "t"]' or "['ctrl', 'c']"
        if (s.startswith("[") and s.endswith("]")) or (s.startswith("(") and s.endswith(")")):
            try:
                import json
                parsed = json.loads(s.replace("'", '"'))
                if isinstance(parsed, list):
                    return [str(k).strip().strip("'\"") for k in parsed if str(k).strip().strip("'\"")]
            except Exception:
                pass
            s = s[1:-1].strip()
        # Handle plus-delimited e.g. "ctrl+t"
        if "+" in s:
            return [k.strip().strip("'\"") for k in s.split("+") if k.strip().strip("'\"")]
        # Handle comma-delimited e.g. "ctrl, t"
        if "," in s:
            return [k.strip().strip("'\"") for k in s.split(",") if k.strip().strip("'\"")]
        # Single key as string
        cleaned = s.strip().strip("'\"[]")
        return [cleaned] if cleaned else []
    elif isinstance(keys, (list, tuple)):
        result = []
        for item in keys:
            if isinstance(item, str):
                cleaned = item.strip().strip("'\"")
                if cleaned:
                    result.append(cleaned)
            elif item is not None:
                result.append(str(item))
        return result
    return list(keys) if keys else []


def press_key(key: Any) -> KeyboardResult:
    """
    Press and release a single key.

    Args:
        key: Key name (e.g. 'enter', 'f5', 'escape').
    """
    if isinstance(key, str):
        key = key.strip().strip("'\"[]")
    log.info("[KEYBOARD] press_key(%s)", key)
    try:
        enforce_rate_limit()
        validated = validate_key(str(key))
        resolved = _resolve_key(validated)
        pag = _get_pyautogui()
        pag.press(resolved)
        time.sleep(0.08)
        return KeyboardResult(
            success=True,
            action="press_key",
            detail=f"Pressed '{resolved}'",
        )
    except SafetyError as e:
        return KeyboardResult(success=False, action="press_key", error=str(e))
    except Exception as exc:
        err = f"Key press failed: {exc}"
        log.error("[KEYBOARD] %s", err)
        return KeyboardResult(success=False, action="press_key", error=err)


def hotkey(keys: Any) -> KeyboardResult:
    """
    Press a keyboard shortcut (key combination).

    Args:
        keys: List of key names or shortcut string to press simultaneously
              (e.g. ['ctrl', 'c'], 'ctrl+t', '["ctrl", "t"]').
    """
    normalized = _normalize_keys(keys)
    log.info("[KEYBOARD] hotkey(%s) -> normalized=%s", keys, normalized)
    try:
        enforce_rate_limit()
        if not normalized:
            raise SafetyError("hotkey requires at least one key.")
        resolved = [_resolve_key(validate_key(k)) for k in normalized]
        pag = _get_pyautogui()
        pag.hotkey(*resolved)
        time.sleep(0.08)
        combo = "+".join(resolved)
        return KeyboardResult(
            success=True,
            action="hotkey",
            detail=f"Pressed {combo}",
        )
    except SafetyError as e:
        return KeyboardResult(success=False, action="hotkey", error=str(e))
    except Exception as exc:
        err = f"Hotkey failed: {exc}"
        log.error("[KEYBOARD] %s", err)
        return KeyboardResult(success=False, action="hotkey", error=err)

