"""
Server-side settings for RaspWatch (defaults and optional file).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).resolve().parent.parent
SETTINGS_FILE = CONFIG_DIR / "settings.json"

DEFAULTS = {
    "refresh_interval_sec": 3,
    "log_lines": 200,
    "log_default_source": "journal",
    "log_file_path": "",
    "theme": "dark",
    "copyright": "© 2026 TheD3vil",
    "alerts_enabled": False,
    "cpu_warn": 90,
    "temp_warn": 80,
    "disk_warn": 90,
    "webhook_url": "",
}


def load_settings() -> dict[str, Any]:
    """Load settings from file or env, merge with defaults."""
    out = dict(DEFAULTS)
    out["log_file_path"] = os.environ.get("RASPWATCH_LOG_FILE", "")
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if k in out:
                    out[k] = v
        except (json.JSONDecodeError, OSError):
            pass
    return out


def save_settings(data: dict[str, Any]) -> dict[str, Any]:
    """Save allowed settings to file. Returns current merged settings."""
    current = load_settings()
    allowed = set(DEFAULTS.keys())
    for k, v in data.items():
        if k in allowed:
            current[k] = v
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {k: current[k] for k in allowed if k not in ("copyright",)},
                f,
                indent=2,
            )
    except OSError:
        pass
    return current
