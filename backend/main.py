"""
RaspWatch - Modern web server and API for Raspberry Pi 5 / Linux.
Compatible with RPi-Monitor style endpoints: dynamic.json, static.json.
Copyright 2026 TheD3vil
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, Query
from fastapi.staticfiles import StaticFiles

from monitor.collectors import collect_dynamic, collect_static
from monitor.history import get_history, init_db, write_snapshot
from monitor.logs_reader import get_logs
from monitor.settings_manager import load_settings, save_settings

HISTORY_INTERVAL = 30
_history_stop = threading.Event()


def _history_worker() -> None:
    init_db()
    try:
        write_snapshot(collect_dynamic())
    except Exception:
        pass
    while not _history_stop.wait(timeout=HISTORY_INTERVAL):
        try:
            write_snapshot(collect_dynamic())
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=_history_worker, daemon=True)
    t.start()
    yield
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
        "history": "/api/history",
        "settings": "/api/settings",
        "copyright": "© 2026 TheD3vil",
    }


@app.get("/dynamic.json")
async def dynamic_json():
    """Live metrics (like XavierBerger RPi-Monitor)."""
    return collect_dynamic()


@app.get("/static.json")
async def static_json():
    """Static host info (like RPi-Monitor)."""
    return collect_static()


@app.get("/api/status")
async def api_status():
    """REST alias for dynamic data."""
    return collect_dynamic()


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
