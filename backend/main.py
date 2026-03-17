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
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from core.auth import create_access_token, require_auth_if_enabled, require_ws_auth_if_enabled, set_token_cookie
from core.event_bus import EventBus
from core.plugin_manager import PluginManager
from monitor.alerts import acknowledge_alerts, check_alerts, get_alert_status, get_and_clear_notify_now, set_last_notify_now
from monitor.collectors import collect_dynamic, collect_static
from monitor.history import get_history, init_db, write_snapshot
from monitor.logs_reader import get_logs
from monitor.analytics import compare as analytics_compare, predict_time_to_threshold, trend as analytics_trend
from monitor.sessions import add_event, end_session, get_session, list_events, list_sessions, start_session
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
_event_bus = EventBus()
_plugins = PluginManager(event_bus=_event_bus)


def _attach_alert_fields(out: dict) -> None:
    """Add alert-related fields to a dynamic payload so the frontend always gets them."""
    status = get_alert_status()
    out["alerts_active"] = status["active"]
    out["alerts_active_unacknowledged"] = status.get("active_unacknowledged", status["active"])
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
            try:
                _plugins.on_sample(data, load_settings())
            except Exception:
                pass
            with _cache_lock:
                _dynamic_cache = data
                _dynamic_cache_ts = time.time()
            try:
                _event_bus.publish("metrics", {"data": copy.deepcopy(data)})
            except Exception:
                pass
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
        try:
            _plugins.on_sample(data, load_settings())
        except Exception:
            pass
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

_REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = _REPO_ROOT / "web" / "dist"
FRONTEND_FALLBACK_DIR = _REPO_ROOT / "frontend"

try:
    _plugins.load_from_settings(app, load_settings())
except Exception:
    pass


@app.middleware("http")
async def _auth_middleware(request: Request, call_next):
    """
    Optional JWT auth gate.

    - Protects API + dynamic/static + SSE by default when enabled.
    - Allows: /, /favicon, /docs, /openapi.json, /health, /api/auth/*
    """
    path = request.url.path or "/"
    if path.startswith(("/docs", "/openapi.json", "/health", "/api/auth")):
        return await call_next(request)
    # Allow static frontend assets
    if path == "/" or path.startswith(("/assets", "/favicon", "/index.html", "/style", "/app")):
        return await call_next(request)
    if path.startswith("/api") or path in ("/dynamic.json", "/static.json"):
        try:
            require_auth_if_enabled(request, load_settings())
        except Exception as exc:
            # FastAPI will convert HTTPException, others become 500; normalize to 401
            from fastapi import HTTPException

            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(status_code=401, detail="Unauthorized")
    return await call_next(request)


@app.post("/api/auth/login")
async def api_auth_login(data: dict = Body(default={})):
    """
    Login for browser/API clients.

    Body: {"api_key": "..."}  (when auth_mode == "api_key")
    Returns: {"access_token": "...", "token_type": "bearer"}
    Also sets an HttpOnly cookie so SSE/EventSource works without headers.
    """
    settings = load_settings()
    if not settings.get("auth_enabled"):
        token = create_access_token(settings)
        resp = Response(
            content=json.dumps({"access_token": token, "token_type": "bearer"}),
            media_type="application/json",
        )
        set_token_cookie(resp, token)
        return resp
    mode = (settings.get("auth_mode") or "api_key").strip()
    if mode != "api_key":
        return Response(content=json.dumps({"error": "auth_mode not supported"}), media_type="application/json", status_code=400)
    provided = (data.get("api_key") or "").strip()
    expected = (settings.get("auth_api_key") or "").strip()
    if not expected or not secrets.compare_digest(provided, expected):
        return Response(content=json.dumps({"error": "invalid credentials"}), media_type="application/json", status_code=401)
    token = create_access_token(settings)
    resp = Response(
        content=json.dumps({"access_token": token, "token_type": "bearer"}),
        media_type="application/json",
    )
    set_token_cookie(resp, token)
    return resp


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """
    WebSocket for bidirectional realtime.

    Auth: cookie `raspwatch_token` (preferred) or `?token=...`.
    Server messages:
      - {"type":"metrics","payload":{...}}
    Client messages (initial set):
      - {"type":"alerts:ack","keys":[...]}  or {"type":"alerts:ack"}
    """
    settings = load_settings()
    try:
        require_ws_auth_if_enabled(ws, settings)
    except Exception:
        await ws.close(code=4401)
        return

    await ws.accept()

    send_lock = asyncio.Lock()

    async def send_json(obj: dict):
        async with send_lock:
            try:
                await ws.send_text(json.dumps(obj))
            except Exception:
                pass

    async def on_metrics(ev):
        payload = ev.payload.get("data")
        if isinstance(payload, dict):
            payload = copy.deepcopy(payload)
            payload.pop("_stale", None)
            await send_json({"type": "metrics", "payload": payload})

    _event_bus.subscribe("metrics", on_metrics)
    async def on_autodarts(ev):
        await send_json({"type": "autodarts:event", "payload": ev.payload})
    _event_bus.subscribe("autodarts:event", on_autodarts)

    # Push latest snapshot immediately (if available)
    snap = get_cached_dynamic()
    if snap:
        snap = copy.deepcopy(snap)
        snap.pop("_stale", None)
        await send_json({"type": "metrics", "payload": snap})

    try:
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            t = data.get("type")
            if t == "alerts:ack":
                keys = data.get("keys") if isinstance(data.get("keys"), list) else None
                try:
                    acknowledge_alerts(keys)
                except Exception:
                    pass
                await send_json({"type": "alerts:ack:ok", "payload": {"ok": True}})
            else:
                await send_json({"type": "error", "payload": {"message": "unknown message type"}})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _event_bus.unsubscribe_all("metrics")
        _event_bus.unsubscribe_all("autodarts:event")
        try:
            await ws.close()
        except Exception:
            pass


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
        "plugins": _plugins.loaded_names,
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


@app.post("/api/alerts/ack")
async def api_alerts_ack(data: dict = Body(default={})):
    """Alerts quitieren: body {} = alle aktiven; body {"keys": ["temp_high", ...]} = nur diese."""
    keys = data.get("keys") if isinstance(data.get("keys"), list) else None
    acknowledge_alerts(keys)
    return {"ok": True, "acknowledged": list(get_alert_status().get("active", [])) if not keys else keys}


@app.get("/api/settings")
async def api_settings_get():
    """Get server settings (defaults + file)."""
    return load_settings()


@app.post("/api/settings")
async def api_settings_post(data: dict = Body(default={})):
    """Update server settings (persisted to settings.json)."""
    return save_settings(data)


@app.post("/api/sessions/start")
async def api_sessions_start(data: dict = Body(default={})):
    kind = (data.get("kind") or "generic").strip()
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    return start_session(kind=kind, meta=meta)


@app.post("/api/sessions/end")
async def api_sessions_end(data: dict = Body(default={})):
    sid = data.get("id")
    try:
        sid = int(sid)
    except Exception:
        return Response(content=json.dumps({"error": "invalid id"}), media_type="application/json", status_code=400)
    out = end_session(session_id=sid)
    if not out:
        return Response(content=json.dumps({"error": "not found"}), media_type="application/json", status_code=404)
    return out


@app.get("/api/sessions")
async def api_sessions_list(kind: str | None = Query(None), limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    return {"data": list_sessions(kind=kind, limit=limit, offset=offset)}


@app.get("/api/sessions/{session_id}")
async def api_sessions_get(session_id: int):
    s = get_session(session_id=session_id)
    if not s:
        return Response(content=json.dumps({"error": "not found"}), media_type="application/json", status_code=404)
    return s


@app.post("/api/sessions/{session_id}/events")
async def api_sessions_add_event(session_id: int, data: dict = Body(default={})):
    event_type = (data.get("type") or "event").strip()
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    return add_event(session_id=session_id, event_type=event_type, payload=payload)


@app.get("/api/sessions/{session_id}/events")
async def api_sessions_list_events(session_id: int, limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0)):
    return {"data": list_events(session_id=session_id, limit=limit, offset=offset)}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/analytics/compare")
async def api_analytics_compare(metric: str = Query("cpu"), period: str = Query("today")):
    allowed = {"cpu", "mem", "swap", "disk", "temp_cpu", "temp_pmic", "temp_rp1"}
    if metric not in allowed:
        return Response(content=json.dumps({"error": "invalid metric"}), media_type="application/json", status_code=400)
    if period not in {"today", "yesterday", "week", "month"}:
        return Response(content=json.dumps({"error": "invalid period"}), media_type="application/json", status_code=400)
    return analytics_compare(metric=metric, period=period)  # type: ignore[arg-type]


@app.get("/api/analytics/trend")
async def api_analytics_trend(metric: str = Query("cpu"), window_min: int = Query(30, ge=5, le=24 * 60)):
    allowed = {"cpu", "mem", "swap", "disk", "temp_cpu", "temp_pmic", "temp_rp1"}
    if metric not in allowed:
        return Response(content=json.dumps({"error": "invalid metric"}), media_type="application/json", status_code=400)
    return analytics_trend(metric=metric, window_min=window_min)  # type: ignore[arg-type]


@app.get("/api/analytics/predict")
async def api_analytics_predict(metric: str = Query("mem"), threshold: float = Query(90), window_min: int = Query(60, ge=5, le=24 * 60)):
    allowed = {"cpu", "mem", "swap", "disk", "temp_cpu", "temp_pmic", "temp_rp1"}
    if metric not in allowed:
        return Response(content=json.dumps({"error": "invalid metric"}), media_type="application/json", status_code=400)
    return predict_time_to_threshold(metric=metric, threshold=float(threshold), window_min=window_min)  # type: ignore[arg-type]


# Static files (frontend) – mount last so API routes take precedence
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
elif FRONTEND_FALLBACK_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_FALLBACK_DIR), html=True), name="frontend_legacy")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 9090))
    log_level = os.environ.get("LOG_LEVEL", "info")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level=log_level)
