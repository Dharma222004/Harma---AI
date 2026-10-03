"""
Harma Runtime V3 — Checkpoints (spec §54)

Run state is persisted as JSON at meaningful boundaries (after planning, after side
effects, after verification, before confirmation, before pause, after recovery, after
completion) to support pause / resume / cancel / crash recovery.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from harma.config.logging_config import get_logger
from harma.core.v3.state import HarmaRunState, TERMINAL_STATUSES, RunStatus

log = get_logger(__name__)


class CheckpointStore:
    def __init__(self, directory: Optional[str] = None, keep: int = 200, enabled: bool = True) -> None:
        if directory is None:
            from harma.config.settings import ROOT_DIR
            directory = str(Path(ROOT_DIR) / "data" / "v3_runs")
        self.dir = Path(directory)
        self.keep = keep
        self.enabled = enabled
        self._writes = 0

    def _path(self, run_id: str) -> Path:
        safe = "".join(c for c in run_id if c.isalnum() or c in "-_")
        return self.dir / f"{safe}.json"

    def save(self, state: HarmaRunState, reason: str) -> None:
        if not self.enabled:
            return
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            data = state.to_dict()
            data["_checkpoint"] = {"reason": reason, "t": time.time()}
            data["events"] = data.get("events", [])[-50:]
            tmp = self._path(state.run_id).with_suffix(".tmp")
            tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
            os.replace(tmp, self._path(state.run_id))
            self._writes += 1
            if self._writes % 25 == 0:
                self.prune()
        except Exception as exc:
            log.debug("[V3][CHECKPOINT] save failed (%s): %s", reason, exc)

    def load(self, run_id: str) -> Optional[HarmaRunState]:
        p = self._path(run_id)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            data.pop("_checkpoint", None)
            return HarmaRunState.from_dict(data)
        except Exception as exc:
            log.warning("[V3][CHECKPOINT] load failed for %s: %s", run_id, exc)
            return None

    def list_resumable(self) -> list[dict[str, Any]]:
        """Runs interrupted by pause or crash (non-terminal)."""
        out = []
        if not self.dir.exists():
            return out
        terminal = {s.value for s in TERMINAL_STATUSES}
        for p in sorted(self.dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:50]:
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if d.get("status") not in terminal:
                out.append({"run_id": d.get("run_id"), "status": d.get("status"),
                            "request": d.get("raw_request", "")[:120],
                            "paused": d.get("status") == RunStatus.PAUSED.value})
        return out

    def prune(self) -> None:
        try:
            files = sorted(self.dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
            for p in files[self.keep:]:
                p.unlink(missing_ok=True)
        except Exception:
            pass
