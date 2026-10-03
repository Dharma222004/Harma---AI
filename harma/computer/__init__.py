"""
Harma Computer Control Package

Low-level computer control layer.
These modules talk directly to the OS / pyautogui / win32 API.
The harma/tools/computer/ layer wraps them into BaseTool subclasses.

Package structure:
    harma/computer/
        controller.py   — orchestrator, safety guard, coordinate validation
        screen.py       — screenshot, dimensions, screen observation
        mouse.py        — mouse movement, clicks, scroll, drag
        keyboard.py     — typing, key press, hotkeys
        windows.py      — window focus, list, active window info
        safety.py       — safety checks, bounds validation, rate limiting
"""
