"""
Log reader for RPiMonitor: journalctl and optional log file.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_LINES = 200
LOG_FILE_ENV = "RPIMONITOR_LOG_FILE"


def get_logs_journal(lines: int = DEFAULT_LINES) -> dict[str, Any]:
    """Fetch recent lines from systemd journal (journalctl)."""
    try:
        r = subprocess.run(
            ["journalctl", "-n", str(lines), "--no-pager", "-o", "short-iso"],
            capture_output=True,
            text=True,
            timeout=5,
            env={**os.environ, "LANG": "C"},
        )
        if r.returncode != 0:
            return {"source": "journal", "lines": [], "error": r.stderr or "journalctl failed"}
        log_lines = [s for s in (r.stdout or "").strip().split("\n") if s.strip()]
        return {"source": "journal", "lines": log_lines[-lines:], "error": None}
    except FileNotFoundError:
        return {"source": "journal", "lines": [], "error": "journalctl not found"}
    except subprocess.TimeoutExpired:
        return {"source": "journal", "lines": [], "error": "Timeout"}


def get_logs_file(path: str | None, lines: int = DEFAULT_LINES) -> dict[str, Any]:
    """Read last N lines from a log file (e.g. /var/log/syslog)."""
    path = path or os.environ.get(LOG_FILE_ENV, "")
    if not path or not os.path.isfile(path):
        return {"source": "file", "path": path or "(not set)", "lines": [], "error": "File not found or not set"}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        log_lines = [s.rstrip("\n\r") for s in all_lines[-lines:] if s.strip()]
        return {"source": "file", "path": path, "lines": log_lines, "error": None}
    except PermissionError:
        return {"source": "file", "path": path, "lines": [], "error": "Permission denied"}
    except OSError as e:
        return {"source": "file", "path": path, "lines": [], "error": str(e)}


def get_logs(source: str = "journal", lines: int = DEFAULT_LINES, log_file_path: str | None = None) -> dict[str, Any]:
    """Get logs from journal or file. source: 'journal' | 'file'."""
    lines = max(1, min(1000, lines))
    if source == "file":
        return get_logs_file(log_file_path, lines)
    return get_logs_journal(lines)
