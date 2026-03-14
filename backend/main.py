"""
RaspWatch - Modern web server and API for Raspberry Pi 5 / Linux.
Compatible with RPi-Monitor style endpoints: dynamic.json, static.json.
Copyright 2026 TheD3vil
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, Query
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from monitor.alerts import check_alerts, get_alert_status, get_and_clear_notify_now, set_last_notify_now
from monitor.collectors import collect_dynamic, collect_static
from monitor.history import get_history, init_db, write_snapshot
from monitor.logs_reader import get_logs
from monitor.settings_manager import load_settings, save_settings

SAMPLER_INTERVAL = 3
SAMPLER_INTERVAL_FAST = 1  # when alert repeat interval is 1–2 s
HISTORY_INTERVAL = 30
_dynamic_cache: dict | None = None
_dynamic_cache_ts: float = 0
_cache_lock = threading.Lock()
_history_stop = threading.Event()
_sampler_stop = threading.Event()
_current_sampler_interval: float = SAMPLER_INTERVAL


def _attach_alert_fields(out: dict) -> None:
    """Add alert-related fields to a dynamic payload so the frontend always gets them."""
    status = get_alert_status()
    out["alerts_active"] = status["active"]
    out["alerts_notify_now"] = get_and_clear_notify_now()
    out["alerts_sound"] = load_settings().get("alerts_sound", True)
    out["alerts_log"] = status["log"]


def get_cached_dynamic() -> dict | None:
    """Return a copy of the last sampled dynamic data, or None if not yet sampled."""
    with _cache_lock:
        if _dynamic_cache is None:
            return None
        out = copy.deepcopy(_dynamic_cache)
        out["_stale"] = (time.time() - _dynamic_cache_ts) > (SAMPLER_INTERVAL * 3)
    _attach_alert_fields(out)
    return out


def _get_sampler_interval() -> float:
    """Use 1 s when alerts are enabled and any repeat interval is 1 or 2 seconds."""
    s = load_settings()
    if not s.get("alerts_enabled"):
        return SAMPLER_INTERVAL
    for key in (
        "cpu_high_interval_sec", "cpu_low_interval_sec",
        "temp_high_interval_sec", "temp_low_interval_sec",
        "disk_high_interval_sec", "mem_high_interval_sec",
    ):
        v = s.get(key)
        if v is not None:
            try:
                n = float(v)
                if 0 < n <= 2:
                    return SAMPLER_INTERVAL_FAST
            except (TypeError, ValueError):
                pass
    return SAMPLER_INTERVAL


def _sampler_loop() -> None:
    global _dynamic_cache, _dynamic_cache_ts, _current_sampler_interval
    init_db()
    tick = 0
    while True:
        _current_sampler_interval = _get_sampler_interval()
        if _sampler_stop.wait(timeout=_current_sampler_interval):
            break
        try:
            data = collect_dynamic()
            with _cache_lock:
                _dynamic_cache = data
                _dynamic_cache_ts = time.time()
            try:
                _active, _notify = check_alerts(data, load_settings())
                set_last_notify_now(_notify)
            except Exception:
                pass
            tick += 1
            if tick >= (HISTORY_INTERVAL // max(1, int(_current_sampler_interval))):
                tick = 0
                try:
                    write_snapshot(data)
                except Exception:
                    pass
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # First sample to fill cache immediately
    try:
        data = collect_dynamic()
        with _cache_lock:
            global _dynamic_cache, _dynamic_cache_ts
            _dynamic_cache = data
            _dynamic_cache_ts = time.time()
        write_snapshot(data)
        _active, _notify = check_alerts(data, load_settings())
        set_last_notify_now(_notify)
    except Exception:
        pass
    t = threading.Thread(target=_sampler_loop, daemon=True)
    t.start()
    yield
    _sampler_stop.set()
    _history_stop.set()


app = FastAPI(
    title="RaspWatch",
    description="Modern real-time monitoring for Raspberry Pi 5 and Linux",
    version="1.2.0",
    lifespan=lifespan,
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/api")
async def api_info_root():
    """API info."""
    return {
        "message": "RaspWatch API",
        "docs": "/docs",
        "dynamic": "/dynamic.json",
        "static": "/static.json",
        "logs": "/api/logs",
        "stream": "/api/stream",
        "alerts": "/api/alerts",
        "history": "/api/history",
        "settings": "/api/settings",
        "copyright": "© 2026 TheD3vil",
    }


@app.get("/dynamic.json")
async def dynamic_json():
    """Live metrics (cached; like XavierBerger RPi-Monitor)."""
    out = get_cached_dynamic()
    if out is not None:
        return out
    out = collect_dynamic()
    _attach_alert_fields(out)
    return out


@app.get("/static.json")
async def static_json():
    """Static host info (like RPi-Monitor)."""
    return collect_static()


@app.get("/api/status")
async def api_status():
    """REST alias for dynamic data (cached)."""
    out = get_cached_dynamic()
    if out is not None:
        return out
    out = collect_dynamic()
    _attach_alert_fields(out)
    return out


async def _sse_generator():
    while True:
        out = get_cached_dynamic()
        if out is not None:
            payload = copy.deepcopy(out)
            payload.pop("_stale", None)
            yield f"data: {json.dumps(payload)}\n\n"
        await asyncio.sleep(_current_sampler_interval)


@app.get("/api/stream")
async def api_stream():
    """SSE stream of cached dynamic data (live updates without polling)."""
    return StreamingResponse(
        _sse_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@app.get("/api/info")
async def api_info():
    """REST alias for static data."""
    return collect_static()


@app.get("/api/logs")
async def api_logs(
    source: str = Query("journal", description="journal or file"),
    lines: int = Query(200, ge=1, le=1000),
):
    """System logs (journalctl or optional log file)."""
    return get_logs(source=source, lines=lines)


@app.get("/api/history")
async def api_history(period: str = Query("1h", description="1h, 6h, 24h, 7d")):
    """Time-series metrics for charts."""
    return {"data": get_history(period=period)}


@app.get("/api/export/history.csv")
async def api_export_history_csv(period: str = Query("24h", description="1h, 6h, 24h, 7d")):
    """Export history as CSV download."""
    rows = get_history(period=period)
    lines = ["ts,datetime,cpu,mem,swap,disk,temp_cpu,temp_pmic,temp_rp1"]
    for r in rows:
        dt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"])) if r.get("ts") else ""
        lines.append(
            f"{r.get('ts', '')},{dt},{r.get('cpu', '')},{r.get('mem', '')},{r.get('swap', '')},"
            f"{r.get('disk', '')},{r.get('temp_cpu', '')},{r.get('temp_pmic', '')},{r.get('temp_rp1', '')}"
        )
    body = "\n".join(lines).encode("utf-8")
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=raspwatch_history.csv"},
    )


@app.get("/api/export/history.json")
async def api_export_history_json(period: str = Query("24h", description="1h, 6h, 24h, 7d")):
    """Export history as JSON download."""
    data = get_history(period=period)
    body = json.dumps({"data": data}, indent=2).encode("utf-8")
    return Response(
        content=body,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=raspwatch_history.json"},
    )


@app.get("/api/alerts")
async def api_alerts():
    """Active alerts and recent alert log."""
    return get_alert_status()


@app.get("/api/settings")
async def api_settings_get():
    """Get server settings (defaults + file)."""
    return load_settings()


@app.post("/api/settings")
async def api_settings_post(data: dict = Body(default={})):
    """Update server settings (persisted to settings.json)."""
    return save_settings(data)


@app.get("/health")
async def health():
    return {"status": "ok"}


# Static files (frontend) – mount last so API routes take precedence
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 9090))
    uvicorn.run(app, host="0.0.0.0", port=port)
