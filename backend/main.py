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

from monitor.alerts import check_alerts, get_alert_status
from monitor.collectors import collect_dynamic, collect_static
from monitor.history import get_history, init_db, write_snapshot
from monitor.logs_reader import get_logs
from monitor.settings_manager import load_settings, save_settings

SAMPLER_INTERVAL = 3
HISTORY_INTERVAL = 30
_dynamic_cache: dict | None = None
_dynamic_cache_ts: float = 0
_cache_lock = threading.Lock()
_history_stop = threading.Event()
_sampler_stop = threading.Event()


def get_cached_dynamic() -> dict | None:
    """Return a copy of the last sampled dynamic data, or None if not yet sampled."""
    with _cache_lock:
        if _dynamic_cache is None:
            return None
        out = copy.deepcopy(_dynamic_cache)
        out["_stale"] = (time.time() - _dynamic_cache_ts) > (SAMPLER_INTERVAL * 3)
    out["alerts_active"] = get_alert_status()["active"]
    return out


def _sampler_loop() -> None:
    global _dynamic_cache, _dynamic_cache_ts
    init_db()
    tick = 0
    while not _sampler_stop.wait(timeout=SAMPLER_INTERVAL):
        try:
            data = collect_dynamic()
            with _cache_lock:
                _dynamic_cache = data
                _dynamic_cache_ts = time.time()
            try:
                check_alerts(data, load_settings())
            except Exception:
                pass
            tick += 1
            if tick >= (HISTORY_INTERVAL // SAMPLER_INTERVAL):
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
        check_alerts(data, load_settings())
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
    return collect_dynamic()


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
    return collect_dynamic()


async def _sse_generator():
    while True:
        out = get_cached_dynamic()
        if out is not None:
            payload = copy.deepcopy(out)
            payload.pop("_stale", None)
            yield f"data: {json.dumps(payload)}\n\n"
        await asyncio.sleep(SAMPLER_INTERVAL)


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
