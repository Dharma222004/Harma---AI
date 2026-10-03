"""
Harma Windows Module

Window management: list, focus, get active window.
Uses pygetwindow (cross-platform) with win32gui fallback on Windows.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Optional

from harma.config.logging_config import get_logger

log = get_logger(__name__)


@dataclass
class WindowInfo:
    """Structured information about a window."""
    title: str
    app: str = ""
    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0
    is_active: bool = False
    is_minimized: bool = False

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "app": self.app,
            "geometry": {"left": self.left, "top": self.top,
                         "width": self.width, "height": self.height},
            "is_active": self.is_active,
            "is_minimized": self.is_minimized,
        }

    def to_text(self) -> str:
        return (
            f"Window: '{self.title}'  "
            f"app={self.app or 'unknown'}  "
            f"geometry=({self.left},{self.top} {self.width}x{self.height})  "
            f"minimized={self.is_minimized}"
        )


def ensure_default_desktop() -> bool:
    """
    Ensure the current thread is attached to the interactive 'Default' desktop on WinSta0.
    In environments where python runs under a secondary/service/sandbox desktop (e.g. IDE subshell),
    window enumeration and focus otherwise return empty or target the wrong desktop.
    """
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        u32 = ctypes.windll.user32
        h_desk = u32.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
        buf = ctypes.create_unicode_buffer(256)
        u32.GetUserObjectInformationW(h_desk, 2, buf, 256, None)
        if buf.value.lower() == "default":
            return True
        h_default = u32.OpenDesktopW("Default", 0, False, 0x01FF)
        if not h_default:
            h_default = u32.OpenDesktopW("Default", 0, False, 0x00C1)
        if h_default:
            return bool(u32.SetThreadDesktop(h_default))
    except Exception as exc:
        log.debug("[WINDOWS] ensure_default_desktop error: %s", exc)
    return False


def get_active_window_info() -> dict:
    """
    Return information about the currently active window.

    Returns:
        dict with 'title', 'app', 'geometry' keys.
    """
    log.debug("[WINDOWS] Getting active window info")

    if sys.platform == "win32":
        return _get_active_window_win32()
    else:
        return _get_active_window_pygetwindow()


def _get_active_window_win32() -> dict:
    """Windows-specific active window detection via win32gui."""
    try:
        ensure_default_desktop()
        import win32gui
        import win32process
        import psutil

        hwnd = win32gui.GetForegroundWindow()
        if not hwnd or not win32gui.IsWindow(hwnd):
            return {"title": "", "app": "", "geometry": {}}

        title = win32gui.GetWindowText(hwnd)
        rect = win32gui.GetWindowRect(hwnd)

        # Get process name
        app = ""
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid)
            app = proc.name()
        except Exception:
            pass

        left, top, right, bottom = rect
        return {
            "title": title,
            "app": app,
            "hwnd": hwnd,
            "geometry": {
                "left": left, "top": top,
                "width": right - left, "height": bottom - top,
            },
        }
    except ImportError:
        log.debug("[WINDOWS] win32gui not available, trying pygetwindow")
        return _get_active_window_pygetwindow()
    except Exception as exc:
        log.warning("[WINDOWS] Could not get active window: %s", exc)
        return {"title": "", "app": "", "geometry": {}}


def _get_active_window_pygetwindow() -> dict:
    """Cross-platform active window via pygetwindow."""
    try:
        import pygetwindow as gw
        win = gw.getActiveWindow()
        if win:
            return {
                "title": win.title,
                "app": "",
                "geometry": {
                    "left": win.left, "top": win.top,
                    "width": win.width, "height": win.height,
                },
            }
    except Exception as exc:
        log.warning("[WINDOWS] pygetwindow error: %s", exc)
    return {"title": "", "app": "", "geometry": {}}


def list_windows(filter_empty: bool = True) -> list[dict]:
    """
    Return a list of all visible windows.

    Args:
        filter_empty: Skip windows with empty titles (default True).

    Returns:
        List of window info dicts.
    """
    log.debug("[WINDOWS] Listing open windows")

    if sys.platform == "win32":
        return _list_windows_win32(filter_empty)
    else:
        return _list_windows_pygetwindow(filter_empty)


def _list_windows_win32(filter_empty: bool) -> list[dict]:
    try:
        ensure_default_desktop()
        import win32gui

        windows = []

        def callback(hwnd, _):
            try:
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if filter_empty and not title.strip():
                        return True
                    rect = win32gui.GetWindowRect(hwnd)
                    left, top, right, bottom = rect
                    windows.append({
                        "title": title,
                        "hwnd": hwnd,
                        "geometry": {
                            "left": left, "top": top,
                            "width": right - left, "height": bottom - top,
                        },
                    })
            except Exception:
                pass
            return True

        win32gui.EnumWindows(callback, None)
        return windows
    except ImportError:
        return _list_windows_pygetwindow(filter_empty)
    except Exception as exc:
        log.warning("[WINDOWS] Could not list windows: %s", exc)
        return _list_windows_pygetwindow(filter_empty)


def _list_windows_pygetwindow(filter_empty: bool) -> list[dict]:
    try:
        import pygetwindow as gw
        windows = []
        for win in gw.getAllWindows():
            if filter_empty and not win.title.strip():
                continue
            windows.append({
                "title": win.title,
                "geometry": {
                    "left": win.left, "top": win.top,
                    "width": win.width, "height": win.height,
                },
            })
        return windows
    except Exception as exc:
        log.warning("[WINDOWS] Could not list windows via pygetwindow: %s", exc)
        return []


def focus_window(title_fragment: str, wait_seconds: float = 3.0) -> dict:
    """
    Focus a window whose title contains the given fragment.

    Args:
        title_fragment: Case-insensitive substring of the window title.
        wait_seconds: How long to wait for the window to appear.

    Returns:
        dict with 'success', 'title', 'error'.
    """
    log.info("[WINDOWS] Focusing window containing '%s'", title_fragment)
    deadline = time.monotonic() + wait_seconds
    fragment_lower = title_fragment.lower()
    poll_interval = 0.05

    while time.monotonic() < deadline:
        if sys.platform == "win32":
            result = _focus_window_win32(fragment_lower)
        else:
            result = _focus_window_pygetwindow(fragment_lower)

        if result["success"]:
            return result
        time.sleep(poll_interval)
        poll_interval = min(poll_interval * 1.5, 0.20)

    return {
        "success": False,
        "title": "",
        "error": f"No window containing '{title_fragment}' found within {wait_seconds}s.",
    }


def _focus_window_win32(fragment_lower: str) -> dict:
    try:
        ensure_default_desktop()
        import win32gui
        import win32con
        import win32process
        import win32api
        import ctypes

        matching_windows: list[tuple[int, Any, str]] = []

        def callback(hwnd, _):
            try:
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if not title.strip():
                        return True
                    t_low = title.lower()
                    if fragment_lower in t_low:
                        cls = win32gui.GetClassName(hwnd)
                        if cls == "#32770" and "dialog" not in fragment_lower:
                            return True  # Skip error/alert dialogs

                        score = 0
                        if t_low == fragment_lower:
                            score = 100
                        elif t_low.startswith(fragment_lower):
                            score = 60
                        else:
                            score = 20

                        # Penalize edition qualifier mismatches (e.g. searching "whatsapp" matching "whatsapp beta")
                        qualifiers = ("beta", "preview", "dev", "canary", "insider", "business")
                        for q in qualifiers:
                            if q in t_low and q not in fragment_lower:
                                score -= 50
                            elif q in fragment_lower and q in t_low:
                                score += 30

                        matching_windows.append((score, hwnd, title))
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(callback, None)
        except Exception:
            pass

        found_hwnd = None
        found_title = ""
        if matching_windows:
            matching_windows.sort(key=lambda x: x[0], reverse=True)
            found_hwnd = matching_windows[0][1]
            found_title = matching_windows[0][2]

        if found_hwnd:
            # 1. Restore if minimized
            if win32gui.IsIconic(found_hwnd):
                win32gui.ShowWindow(found_hwnd, win32con.SW_RESTORE)
            else:
                win32gui.ShowWindow(found_hwnd, win32con.SW_SHOW)

            # 2. Attach thread inputs to bypass Windows focus-stealing prevention
            fg_hwnd = win32gui.GetForegroundWindow()
            fg_tid = win32process.GetWindowThreadProcessId(fg_hwnd)[0] if fg_hwnd else 0
            cur_tid = win32api.GetCurrentThreadId()
            target_tid = win32process.GetWindowThreadProcessId(found_hwnd)[0]

            attached_fg = False
            attached_cur = False
            try:
                if fg_tid and fg_tid != target_tid:
                    try:
                        win32process.AttachThreadInput(fg_tid, target_tid, True)
                        attached_fg = True
                    except Exception:
                        pass
                if cur_tid != target_tid:
                    try:
                        win32process.AttachThreadInput(cur_tid, target_tid, True)
                        attached_cur = True
                    except Exception:
                        pass

                # Simulate extended Alt key down/up to release OS focus lock
                win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_EXTENDEDKEY | 0, 0)
                win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_EXTENDEDKEY | win32con.KEYEVENTF_KEYUP, 0)

                win32gui.BringWindowToTop(found_hwnd)
                win32gui.SetForegroundWindow(found_hwnd)

                # Use SwitchToThisWindow API
                try:
                    ctypes.windll.user32.SwitchToThisWindow(found_hwnd, True)
                except Exception:
                    pass

                time.sleep(0.15)
            finally:
                if attached_fg:
                    try:
                        win32process.AttachThreadInput(fg_tid, target_tid, False)
                    except Exception:
                        pass
                if attached_cur:
                    try:
                        win32process.AttachThreadInput(cur_tid, target_tid, False)
                    except Exception:
                        pass

            # 3. If window is still not foreground, physically click safe client/title area to force OS focus
            if win32gui.GetForegroundWindow() != found_hwnd:
                try:
                    rect = win32gui.GetWindowRect(found_hwnd)
                    left, top, right, bottom = rect
                    if right > left and bottom > top:
                        import pyautogui
                        click_x = left + min(200, max(50, (right - left) // 4))
                        click_y = top + min(30, max(15, (bottom - top) // 10))
                        prev_pos = pyautogui.position()
                        pyautogui.click(click_x, click_y)
                        pyautogui.moveTo(prev_pos)
                        time.sleep(0.15)
                except Exception as click_err:
                    log.debug("[WINDOWS] Focus click fallback: %s", click_err)

            log.info("[WINDOWS] Focused: '%s'", found_title)
            return {"success": True, "title": found_title, "error": ""}
        return {"success": False, "title": "", "error": f"No window matching '{fragment_lower}' found."}
    except Exception as exc:
        log.warning("[WINDOWS] win32 focus error: %s", exc)
        return _focus_window_pygetwindow(fragment_lower)


def _focus_window_pygetwindow(fragment_lower: str) -> dict:
    try:
        import pygetwindow as gw
        matches = [w for w in gw.getAllWindows() if fragment_lower in w.title.lower()]
        if matches:
            win = matches[0]
            try:
                win.restore()
            except Exception:
                pass
            try:
                win.activate()
            except Exception:
                pass
            time.sleep(0.2)
            return {"success": True, "title": win.title, "error": ""}
        return {"success": False, "title": "", "error": f"No window matching '{fragment_lower}' found."}
    except Exception as exc:
        log.warning("[WINDOWS] pygetwindow focus error: %s", exc)
        return {"success": False, "title": "", "error": str(exc)}


def window_exists(title_fragment: str) -> bool:
    """Check if any visible window contains the title fragment."""
    fragment_lower = title_fragment.lower()
    windows = list_windows()
    return any(fragment_lower in w.get("title", "").lower() for w in windows)
