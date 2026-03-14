"""
RaspWatch history storage: SQLite time-series for charts.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

DB_DIR = Path(__file__).resolve().parent.parent
DB_PATH = DB_DIR / "history.db"
RETENTION_DAYS = 7
INTERVAL_SEC = 30


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                ts REAL PRIMARY KEY,
                cpu REAL,
                mem REAL,
                swap REAL,
                disk REAL,
                temp_cpu REAL,
                temp_pmic REAL,
                temp_rp1 REAL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics(ts)")


def write_snapshot(data: dict[str, Any]) -> None:
    d = data
    cpu = (d.get("cpu") or {}).get("usage_percent")
    mem = (d.get("memory") or {}).get("usage_percent")
    swap = (d.get("swap") or {}).get("usage_percent")
    disk = (d.get("disk") or {}).get("usage_percent")
    temp = d.get("temperature") or {}
    temp_cpu = temp.get("cpu")
    temp_pmic = temp.get("pmic")
    temp_rp1 = temp.get("rp1")
    ts = time.time()
    with _get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO metrics (ts, cpu, mem, swap, disk, temp_cpu, temp_pmic, temp_rp1)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (ts, cpu, mem, swap, disk, temp_cpu, temp_pmic, temp_rp1),
        )
        cutoff = ts - RETENTION_DAYS * 86400
        conn.execute("DELETE FROM metrics WHERE ts < ?", (cutoff,))


def get_history(period: str = "1h") -> list[dict[str, Any]]:
    """period: 1h, 6h, 24h, 7d"""
    now = time.time()
    if period == "1h":
        start = now - 3600
    elif period == "6h":
        start = now - 6 * 3600
    elif period == "24h":
        start = now - 24 * 3600
    elif period == "7d":
        start = now - 7 * 86400
    else:
        start = now - 3600
    with _get_conn() as conn:
        cur = conn.execute(
            "SELECT ts, cpu, mem, swap, disk, temp_cpu, temp_pmic, temp_rp1 FROM metrics WHERE ts >= ? ORDER BY ts",
            (start,),
        )
        rows = cur.fetchall()
    return [
        {
            "ts": r["ts"],
            "cpu": r["cpu"],
            "mem": r["mem"],
            "swap": r["swap"],
            "disk": r["disk"],
            "temp_cpu": r["temp_cpu"],
            "temp_pmic": r["temp_pmic"],
            "temp_rp1": r["temp_rp1"],
        }
        for r in rows
    ]
