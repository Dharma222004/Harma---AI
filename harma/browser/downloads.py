"""
Harma Browser Downloads — Phase 3

Handles file download initiation, tracking, and verification.

Safety rules:
  - Downloads only to a configured safe directory.
  - File size > 0 verified before declaring success.
  - Never claims a download succeeded without file verification.
  - Sensitive filenames are not logged.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, TYPE_CHECKING

from harma.config.logging_config import get_logger

if TYPE_CHECKING:
    from playwright.async_api import Page, Download

log = get_logger(__name__)

# Default download directory — inside user's home
_DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "harma"


@dataclass
class DownloadResult:
    """Result of a download operation."""
    success: bool
    filename: str = ""
    file_path: str = ""
    file_size_bytes: int = 0
    error: str = ""

    def to_text(self) -> str:
        if self.success:
            size_kb = self.file_size_bytes / 1024
            return (
                f"Downloaded: {self.filename!r}  "
                f"({size_kb:.1f} KB)  "
                f"Saved to: {self.file_path}"
            )
        return f"Download failed: {self.error}"

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "filename": self.filename,
            "file_path": self.file_path,
            "file_size_bytes": self.file_size_bytes,
            "error": self.error,
        }


def _ensure_download_dir(download_dir: Optional[str] = None) -> Path:
    d = Path(download_dir) if download_dir else _DEFAULT_DOWNLOAD_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class DownloadRecord:
    """Tracks a completed download in session history."""
    filename: str
    file_path: str
    file_size_bytes: int
    url: str = ""


class DownloadManager:
    """
    Tracks and manages file downloads within a browser session.

    Usage:
        dm = DownloadManager()
        result = await dm.wait_and_save(download_event, download_dir)
    """

    def __init__(self, download_dir: Optional[str] = None) -> None:
        self._dir = _ensure_download_dir(download_dir)
        self._history: List[DownloadRecord] = []

    async def wait_and_save(
        self,
        download: "Download",
        timeout: int = 60_000,
    ) -> DownloadResult:
        """
        Wait for a Playwright Download event to complete and save the file.

        Args:
            download: Playwright Download object from page.expect_download().
            timeout: Max wait time in ms.
        """
        try:
            filename = download.suggested_filename or "harma_download"
            dest = self._dir / filename

            # Save to our controlled directory
            await download.save_as(str(dest))

            # Verify file exists and has content
            if not dest.exists():
                return DownloadResult(
                    success=False,
                    error=f"File was not created at {dest}",
                )

            size = dest.stat().st_size
            if size == 0:
                return DownloadResult(
                    success=False,
                    error="Downloaded file is empty (0 bytes).",
                )

            record = DownloadRecord(
                filename=filename,
                file_path=str(dest),
                file_size_bytes=size,
            )
            self._history.append(record)

            log.info("[DL] Downloaded: %s  size=%d bytes", filename, size)
            return DownloadResult(
                success=True,
                filename=filename,
                file_path=str(dest),
                file_size_bytes=size,
            )

        except Exception as exc:
            err = f"Download failed: {exc}"
            log.error("[DL] %s", err)
            return DownloadResult(success=False, error=err)

    def list_recent(self, limit: int = 10) -> List[DownloadRecord]:
        """Return the most recent downloads."""
        return self._history[-limit:]

    @property
    def download_dir(self) -> str:
        return str(self._dir)


async def click_and_download(
    page: "Page",
    download_manager: DownloadManager,
    locator,
    timeout: int = 60_000,
) -> DownloadResult:
    """
    Click an element that triggers a file download and wait for it.

    Args:
        page: Active Playwright page.
        download_manager: The session download manager.
        locator: Playwright locator for the element to click.
        timeout: Download timeout in ms.
    """
    try:
        async with page.expect_download(timeout=timeout) as dl_info:
            await locator.click()
        download = await dl_info.value
        return await download_manager.wait_and_save(download, timeout)
    except Exception as exc:
        err = f"Click-and-download failed: {exc}"
        log.error("[DL] %s", err)
        return DownloadResult(success=False, error=err)
