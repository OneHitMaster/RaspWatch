"""
RaspWatch alerts: threshold checks (high/low), repeat intervals, persistence, webhook, sound flag.
"""
from __future__ import annotations

import json
import time
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any

ALERT_LOG_MAX = 50
_STATE_FILE = Path(__file__).resolve().parent.parent / "alerts_state.json"

# All alert keys: high = above threshold, low = below threshold
ALERT_KEYS = (
    "cpu_high", "cpu_low",
    "temp_high", "temp_low",
    "disk_high",
    "mem_high",
)

_alert_state: dict[str, bool] = {}
_alert_last_notify_ts: dict[str, float] = {}
_alert_log: deque[dict[str, Any]] = deque(maxlen=ALERT_LOG_MAX)
_log_next_id: int = 0
_acknowledged: set[str] = set()  # Quittierte Alerts – keine Wiederholungs-Meldungen mehr bis zur Auflösung
_pending_since: dict[str, float] = {}  # sustained detection: first time condition became true
_last_values: dict[str, float] = {}  # anomaly detection baselines


def _next_log_id() -> int:
    global _log_next_id
    _log_next_id += 1
    return _log_next_id


def _load_persisted() -> None:
    """Load state, last-notify times and log from file."""
    global _alert_state, _alert_last_notify_ts, _alert_log, _log_next_id
    if not _STATE_FILE.exists():
        return
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _alert_state = data.get("state") or {}
        _alert_last_notify_ts = data.get("last_notify_ts") or {}
        log = data.get("log") or []
        _log_next_id = data.get("log_next_id", 0)
        for e in log:
            if e.get("id") is None:
                e["id"] = _next_log_id()
        _alert_log = deque(log[-ALERT_LOG_MAX:], maxlen=ALERT_LOG_MAX)
        if _alert_log:
            _log_next_id = max((e.get("id", 0) for e in _alert_log), default=0) + 1
    except (json.JSONDecodeError, OSError):
        pass


def _save_persisted() -> None:
    """Persist current state, last-notify times and log."""
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "state": _alert_state,
                "last_notify_ts": _alert_last_notify_ts,
                "log": list(_alert_log),
                "log_next_id": _log_next_id,
            }, f, indent=0)
    except OSError:
        pass


_load_persisted()


def _get_float(settings: dict[str, Any], key: str, default: float) -> float:
    v = settings.get(key)
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _get_bool(settings: dict[str, Any], key: str, default: bool = False) -> bool:
    v = settings.get(key)
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def check_alerts(data: dict[str, Any], settings: dict[str, Any]) -> tuple[list[str], list[str]]:
    """
    Check all configured thresholds; update state and log; optionally POST webhook.
    Returns (active_keys, notify_now_keys).
    notify_now_keys: keys that should trigger a notification this cycle (first trigger or interval elapsed).
    """
    if not _get_bool(settings, "alerts_enabled"):
        return [], []

    cpu = (data.get("cpu") or {}).get("usage_percent")
    temp = (data.get("temperature") or {}).get("cpu")
    disk = (data.get("disk") or {}).get("usage_percent")
    mem = (data.get("memory") or {}).get("usage_percent")
    webhook_url = (settings.get("webhook_url") or "").strip()
    now = time.time()
    sustain_sec = _get_float(settings, "alerts_sustain_sec", 10)
    if sustain_sec < 0:
        sustain_sec = 0

    def rule(
        key: str,
        enabled: bool,
        value: float,
        interval_sec: float,
        is_high: bool,
        actual: float | None,
    ) -> bool:
        if not enabled or actual is None:
            return False
        if is_high:
            return actual >= value
        return actual <= value

    # sustained gating: condition must hold for sustain_sec before becoming "active"
    active: list[str] = []
    def sustained(key: str, cond: bool) -> bool:
        if not cond:
            _pending_since.pop(key, None)
            return False
        if sustain_sec <= 0:
            return True
        since = _pending_since.get(key)
        if since is None:
            _pending_since[key] = now
            return False
        return (now - since) >= sustain_sec

    # cpu_high
    cpu_high_cond = rule(
        "cpu_high",
        _get_bool(settings, "cpu_high_enabled", True),
        _get_float(settings, "cpu_high_value", 90),
        0,
        True,
        cpu,
    )
    if sustained("cpu_high", cpu_high_cond):
        active.append("cpu_high")
    # cpu_low
    cpu_low_cond = rule(
        "cpu_low",
        _get_bool(settings, "cpu_low_enabled"),
        _get_float(settings, "cpu_low_value", 10),
        0,
        False,
        cpu,
    )
    if sustained("cpu_low", cpu_low_cond):
        active.append("cpu_low")
    # temp_high
    temp_high_cond = rule(
        "temp_high",
        _get_bool(settings, "temp_high_enabled", True),
        _get_float(settings, "temp_high_value", 80),
        0,
        True,
        temp,
    )
    if sustained("temp_high", temp_high_cond):
        active.append("temp_high")
    # temp_low (e.g. under 40°C)
    temp_low_cond = rule(
        "temp_low",
        _get_bool(settings, "temp_low_enabled"),
        _get_float(settings, "temp_low_value", 40),
        0,
        False,
        temp,
    )
    if sustained("temp_low", temp_low_cond):
        active.append("temp_low")
    # disk_high
    disk_high_cond = rule(
        "disk_high",
        _get_bool(settings, "disk_high_enabled", True),
        _get_float(settings, "disk_high_value", 90),
        0,
        True,
        disk,
    )
    if sustained("disk_high", disk_high_cond):
        active.append("disk_high")
    # mem_high
    mem_high_cond = rule(
        "mem_high",
        _get_bool(settings, "mem_high_enabled"),
        _get_float(settings, "mem_high_value", 90),
        0,
        True,
        mem,
    )
    if sustained("mem_high", mem_high_cond):
        active.append("mem_high")

    notify_now: list[str] = []

    # anomaly: cpu spike (event-only; does not become active)
    if _get_bool(settings, "alerts_anomaly_enabled"):
        try:
            spike = _get_float(settings, "alerts_anomaly_cpu_spike", 30)
            if cpu is not None:
                prev = _last_values.get("cpu")
                _last_values["cpu"] = float(cpu)
                if prev is not None and (float(cpu) - float(prev)) >= spike:
                    entry = {
                        "id": _next_log_id(),
                        "ts": now,
                        "type": "cpu_spike",
                        "event": "anomaly",
                        "message": f"CPU Spike: {prev:.1f}% → {float(cpu):.1f}%",
                    }
                    _alert_log.append(entry)
                    _save_persisted()
                    notify_now.append("cpu_spike")
                    if webhook_url:
                        _post_webhook(webhook_url, entry)
        except Exception:
            pass
    interval_settings = {
        "cpu_high": _get_float(settings, "cpu_high_interval_sec", 0),
        "cpu_low": _get_float(settings, "cpu_low_interval_sec", 0),
        "temp_high": _get_float(settings, "temp_high_interval_sec", 0),
        "temp_low": _get_float(settings, "temp_low_interval_sec", 5),
        "disk_high": _get_float(settings, "disk_high_interval_sec", 0),
        "mem_high": _get_float(settings, "mem_high_interval_sec", 0),
    }

    _LABELS = {
        "cpu_high": "CPU über Schwellwert",
        "cpu_low": "CPU unter Schwellwert",
        "temp_high": "Temperatur über Schwellwert",
        "temp_low": "Temperatur unter Schwellwert",
        "disk_high": "Speicher über Schwellwert",
        "mem_high": "RAM über Schwellwert",
    }

    for key in ALERT_KEYS:
        was = _alert_state.get(key, False)
        is_now = key in active
        interval_sec = interval_settings.get(key, 0)
        last_ts = _alert_last_notify_ts.get(key, 0)
        label = _LABELS.get(key, key)

        if is_now and not was:
            # Just became active (evtl. war vorher quittiert – neu auslösen)
            _acknowledged.discard(key)
            entry = {"id": _next_log_id(), "ts": now, "type": key, "event": "alert", "message": label}
            _alert_log.append(entry)
            _alert_state[key] = True
            _alert_last_notify_ts[key] = now
            _save_persisted()
            notify_now.append(key)
            if webhook_url:
                _post_webhook(webhook_url, entry)
        elif is_now and was:
            # Still active: repeat only if not acknowledged
            if key not in _acknowledged and interval_sec > 0 and (now - last_ts) >= interval_sec:
                _alert_last_notify_ts[key] = now
                _save_persisted()
                notify_now.append(key)
                repeat_entry = {"id": _next_log_id(), "ts": now, "type": key, "event": "repeat", "message": f"{label} (Wiederholung)"}
                _alert_log.append(repeat_entry)
                if webhook_url:
                    _post_webhook(webhook_url, repeat_entry)
        elif not is_now and was:
            # Resolved
            _acknowledged.discard(key)
            entry = {"id": _next_log_id(), "ts": now, "type": key, "event": "resolved", "message": f"{label} – wieder normal"}
            _alert_log.append(entry)
            _alert_state[key] = False
            _alert_last_notify_ts[key] = 0
            _save_persisted()
            if webhook_url:
                _post_webhook(webhook_url, entry)

    return active, notify_now


def _post_webhook(url: str, payload: dict[str, Any]) -> None:
    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def get_alert_status() -> dict[str, Any]:
    """Return active alerts, unacknowledged (for badge), and recent log."""
    active = [k for k in ALERT_KEYS if _alert_state.get(k)]
    unack = [k for k in active if k not in _acknowledged]
    return {
        "active": active,
        "active_unacknowledged": unack,
        "log": list(_alert_log),
    }


def acknowledge_alerts(keys: list[str] | None = None) -> None:
    """Quitieren: keys = None = alle aktuell aktiven; sonst nur die genannten."""
    global _acknowledged
    if not keys:
        _acknowledged = {k for k in ALERT_KEYS if _alert_state.get(k)}
    else:
        _acknowledged |= {k for k in keys if k in ALERT_KEYS}


# Notify_now: set by check_alerts, consumed once per response so each client gets one pop per interval
_last_notify_now: list[str] = []


def set_last_notify_now(keys: list[str]) -> None:
    global _last_notify_now
    _last_notify_now = list(keys)


def get_and_clear_notify_now() -> list[str]:
    """Return and clear notify_now so it is only sent in one response."""
    global _last_notify_now
    out = _last_notify_now
    _last_notify_now = []
    return out
