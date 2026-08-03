"""Shared enrich-job progress file for CLI + dashboard.

Written by scripts/enrich_listing.py after every row; read by the dashboard
at GET /api/enrich/status so https://bd.limlamleen.com can show live progress
even when enrichment runs as a separate systemd/nohup process.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PATH = Path(os.getenv("ENRICH_PROGRESS_PATH", "data/enrich_progress.json"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_state() -> dict:
    return {
        "running": False,
        "pid": None,
        "started_at": None,
        "updated_at": None,
        "finished_at": None,
        "input": None,
        "output": None,
        "sheet": None,
        "total": 0,
        "done": 0,
        "skipped": 0,
        "failed": 0,
        "current_index": 0,
        "current_name": None,
        "current_row": None,
        "last_status": None,  # ok | error | idle
        "last_error": None,
        "recent": [],  # last ~20 {name, status, seconds, at}
    }


def load(path: Path | None = None) -> dict:
    p = path or DEFAULT_PATH
    if not p.exists():
        return default_state()
    try:
        data = json.loads(p.read_text())
    except Exception:
        return default_state()
    base = default_state()
    base.update(data if isinstance(data, dict) else {})
    return base


def save(state: dict, path: Path | None = None) -> None:
    """Atomic write so the dashboard never reads a half-written file."""
    p = path or DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    state = dict(state)
    state["updated_at"] = _now()
    payload = json.dumps(state, ensure_ascii=False, indent=2)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".enrich_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(payload)
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def append_recent(state: dict, entry: dict, keep: int = 20) -> None:
    recent = list(state.get("recent") or [])
    recent.append(entry)
    state["recent"] = recent[-keep:]
