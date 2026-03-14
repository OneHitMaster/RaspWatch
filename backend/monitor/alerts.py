"""
RaspWatch alerts: threshold checks and optional webhook.
"""
from __future__ import annotations

import json
import time
import urllib.request
from collections import deque
from typing import Any

ALERT_LOG_MAX = 50
_alert_state: dict[str, bool] = {}
_alert_log: deque[dict[str, Any]] = deque(maxlen=ALERT_LOG_MAX)


def check_alerts(data: dict[str, Any], settings: dict[str, Any]) -> list[str]:
    """Check thresholds; update state and log; optionally POST webhook. Returns list of active alert keys."""
    if not settings.get("alerts_enabled"):
        return []
    cpu_warn = float(settings.get("cpu_warn") or 90)
    temp_warn = float(settings.get("temp_warn") or 80)
    disk_warn = float(settings.get("disk_warn") or 90)
    webhook_url = (settings.get("webhook_url") or "").strip()

    active: list[str] = []
    cpu = (data.get("cpu") or {}).get("usage_percent")
    if cpu is not None and cpu >= cpu_warn:
        active.append("cpu")
    temp = (data.get("temperature") or {}).get("cpu")
    if temp is not None and temp >= temp_warn:
        active.append("temp")
    disk = (data.get("disk") or {}).get("usage_percent")
    if disk is not None and disk >= disk_warn:
        active.append("disk")

    now = time.time()
    for key in ("cpu", "temp", "disk"):
        was = _alert_state.get(key, False)
        is_now = key in active
        if is_now and not was:
            entry = {"ts": now, "type": key, "event": "alert", "message": f"{key} threshold exceeded"}
            _alert_log.append(entry)
            _alert_state[key] = True
            if webhook_url:
                _post_webhook(webhook_url, entry)
        elif not is_now and was:
            entry = {"ts": now, "type": key, "event": "resolved", "message": f"{key} back to normal"}
            _alert_log.append(entry)
            _alert_state[key] = False
            if webhook_url:
                _post_webhook(webhook_url, entry)

    return active


def _post_webhook(url: str, payload: dict[str, Any]) -> None:
    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def get_alert_status() -> dict[str, Any]:
    """Return active alerts and recent log."""
    return {
        "active": [k for k in ("cpu", "temp", "disk") if _alert_state.get(k)],
        "log": list(_alert_log),
    }
