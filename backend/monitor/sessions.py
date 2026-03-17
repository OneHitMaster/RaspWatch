from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


DB_DIR = Path(__file__).resolve().parent.parent
DB_PATH = DB_DIR / "history.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_sessions_db() -> None:
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                start_ts REAL NOT NULL,
                end_ts REAL,
                meta_json TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_kind_ts ON sessions(kind, start_ts)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                ts REAL NOT NULL,
                type TEXT NOT NULL,
                payload_json TEXT,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_session_ts ON events(session_id, ts)")


def start_session(kind: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    now = time.time()
    meta_json = json.dumps(meta or {}, separators=(",", ":"), ensure_ascii=False)
    with _get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sessions(kind, start_ts, end_ts, meta_json) VALUES (?, ?, NULL, ?)",
            (kind, now, meta_json),
        )
        sid = int(cur.lastrowid)
    return {"id": sid, "kind": kind, "start_ts": now, "end_ts": None, "meta": meta or {}}


def end_session(session_id: int) -> dict[str, Any] | None:
    now = time.time()
    with _get_conn() as conn:
        conn.execute("UPDATE sessions SET end_ts = ? WHERE id = ? AND end_ts IS NULL", (now, session_id))
        cur = conn.execute("SELECT id, kind, start_ts, end_ts, meta_json FROM sessions WHERE id = ?", (session_id,))
        row = cur.fetchone()
    if not row:
        return None
    return _row_to_session(row)


def list_sessions(kind: str | None = None, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    with _get_conn() as conn:
        if kind:
            cur = conn.execute(
                "SELECT id, kind, start_ts, end_ts, meta_json FROM sessions WHERE kind = ? ORDER BY start_ts DESC LIMIT ? OFFSET ?",
                (kind, limit, offset),
            )
        else:
            cur = conn.execute(
                "SELECT id, kind, start_ts, end_ts, meta_json FROM sessions ORDER BY start_ts DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        rows = cur.fetchall()
    return [_row_to_session(r) for r in rows]


def get_session(session_id: int) -> dict[str, Any] | None:
    with _get_conn() as conn:
        cur = conn.execute("SELECT id, kind, start_ts, end_ts, meta_json FROM sessions WHERE id = ?", (session_id,))
        row = cur.fetchone()
    if not row:
        return None
    return _row_to_session(row)


def add_event(session_id: int, event_type: str, payload: dict[str, Any] | None = None, ts: float | None = None) -> dict[str, Any]:
    t = float(ts) if ts is not None else time.time()
    payload_json = json.dumps(payload or {}, separators=(",", ":"), ensure_ascii=False)
    with _get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO events(session_id, ts, type, payload_json) VALUES (?, ?, ?, ?)",
            (session_id, t, event_type, payload_json),
        )
        eid = int(cur.lastrowid)
    return {"id": eid, "session_id": session_id, "ts": t, "type": event_type, "payload": payload or {}}


def list_events(session_id: int, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 200), 2000))
    offset = max(0, int(offset or 0))
    with _get_conn() as conn:
        cur = conn.execute(
            "SELECT id, session_id, ts, type, payload_json FROM events WHERE session_id = ? ORDER BY ts ASC LIMIT ? OFFSET ?",
            (session_id, limit, offset),
        )
        rows = cur.fetchall()
    out = []
    for r in rows:
        payload = {}
        try:
            payload = json.loads(r["payload_json"] or "{}")
        except Exception:
            payload = {}
        out.append(
            {"id": r["id"], "session_id": r["session_id"], "ts": r["ts"], "type": r["type"], "payload": payload}
        )
    return out


def _row_to_session(r: sqlite3.Row) -> dict[str, Any]:
    meta = {}
    try:
        meta = json.loads(r["meta_json"] or "{}")
    except Exception:
        meta = {}
    return {"id": r["id"], "kind": r["kind"], "start_ts": r["start_ts"], "end_ts": r["end_ts"], "meta": meta}

