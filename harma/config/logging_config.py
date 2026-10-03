"""
Harma Logging

Provides a consistent logger factory used across all Harma modules.
Produces colour-coded terminal output + optional file logging.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

# ANSI colour codes (disabled automatically on Windows if not supported)
_COLOURS = {
    "DEBUG": "\033[36m",     # cyan
    "INFO": "\033[32m",      # green
    "WARNING": "\033[33m",   # yellow
    "ERROR": "\033[31m",     # red
    "CRITICAL": "\033[35m",  # magenta
    "RESET": "\033[0m",
}

_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


class _ColourFormatter(logging.Formatter):
    """Formatter that adds ANSI colour codes to the level name."""

    def format(self, record: logging.LogRecord) -> str:
        colour = _COLOURS.get(record.levelname, "")
        reset = _COLOURS["RESET"]
        record.levelname = f"{colour}{record.levelname:8}{reset}"
        return super().format(record)


def get_logger(name: str, level: Optional[int] = None) -> logging.Logger:
    """
    Return a named Harma logger.

    Args:
        name: Usually ``__name__`` of the calling module.
        level: Override log level (default: INFO).
    """
    logger = logging.getLogger(f"harma.{name}")

    if logger.handlers:
        # Already configured — return cached logger
        return logger

    effective_level = level or logging.INFO
    logger.setLevel(effective_level)

    # ── Console handler ──────────────────────────────────────────────────────
    # Force UTF-8 on Windows terminals that default to cp1252
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(effective_level)
    console_handler.setFormatter(
        _ColourFormatter(
            fmt="%(asctime)s  %(levelname)s  %(name)s  |  %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logger.addHandler(console_handler)

    # ── File handler (optional) ───────────────────────────────────────────────
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(_LOG_DIR / "harma.log", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # always verbose on disk
        file_handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s  %(levelname)-8s  %(name)s  |  %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(file_handler)
    except Exception:
        pass  # file logging is optional — don't crash if unavailable

    logger.propagate = False
    return logger
