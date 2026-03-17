from __future__ import annotations

import time
from typing import Any

from fastapi import Body, FastAPI

from core.plugin_base import PluginContext


class AutodartsPlugin:
    name = "autodarts"

    def __init__(self) -> None:
        self._throws: list[dict[str, Any]] = []
        self._scores: list[dict[str, Any]] = []
        self._sessions: list[dict[str, Any]] = []

    def register(self, app: FastAPI, ctx: PluginContext) -> None:
        @app.get("/api/autodarts/sessions")
        async def autodarts_sessions():
            return {"data": list(self._sessions)[-100:]}

        @app.get("/api/autodarts/throws")
        async def autodarts_throws(limit: int = 100):
            limit = max(1, min(int(limit or 100), 1000))
            return {"data": list(self._throws)[-limit:]}

        @app.get("/api/autodarts/scores")
        async def autodarts_scores(limit: int = 100):
            limit = max(1, min(int(limit or 100), 1000))
            return {"data": list(self._scores)[-limit:]}

        @app.post("/api/autodarts/event")
        async def autodarts_event(data: dict = Body(default={})):
            """
            Ingest Autodarts event (stub).
            Expected examples:
              {"type":"game_started","payload":{...}}
              {"type":"throw","payload":{"segment":20,"mult":3}}
              {"type":"one_eighty","payload":{...}}
            """
            ev_type = (data.get("type") or "event").strip()
            payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
            entry = {"ts": time.time(), "type": ev_type, "payload": payload}

            if ev_type in ("game_started", "game_ended"):
                self._sessions.append(entry)
            elif ev_type in ("throw", "dart", "hit"):
                self._throws.append(entry)
            elif ev_type in ("score", "score_update"):
                self._scores.append(entry)

            # publish to websocket consumers
            try:
                ctx.event_bus.publish("autodarts:event", {"event": entry})
            except Exception:
                pass

            # also mirror into generic sessions/events if a session_id is provided
            sid = payload.get("session_id")
            if sid is not None:
                try:
                    from monitor.sessions import add_event

                    add_event(session_id=int(sid), event_type=f"autodarts:{ev_type}", payload=payload)
                except Exception:
                    pass
            return {"ok": True}

    def on_sample(self, dynamic_payload: dict[str, Any], ctx: PluginContext) -> None:
        # Surface small summary on the main dashboard payload
        dynamic_payload["autodarts"] = {
            "throws": len(self._throws),
            "scores": len(self._scores),
            "sessions": len(self._sessions),
        }


plugin = AutodartsPlugin()

