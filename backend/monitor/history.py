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


MAX_POINTS = 150  # Max data points per chart for smooth rendering


def _downsample(rows: list[dict[str, Any]], max_pts: int = MAX_POINTS) -> list[dict[str, Any]]:
    """Reduce to max_pts by averaging in time buckets. Keeps first and last ts per bucket."""
    n = len(rows)
    if n <= max_pts:
        return rows
    result = []
    bucket_size = n / max_pts
    for i in range(max_pts):
        start_idx = int(i * bucket_size)
        end_idx = min(int((i + 1) * bucket_size), n)
        if start_idx >= end_idx:
            continue
        chunk = rows[start_idx:end_idx]
        first = chunk[0]
        avg = {
            "ts": first["ts"],
            "cpu": _avg([r["cpu"] for r in chunk]),
            "mem": _avg([r["mem"] for r in chunk]),
            "swap": _avg([r["swap"] for r in chunk]),
            "disk": _avg([r["disk"] for r in chunk]),
            "temp_cpu": _avg([r["temp_cpu"] for r in chunk]),
            "temp_pmic": _avg([r["temp_pmic"] for r in chunk]),
            "temp_rp1": _avg([r["temp_rp1"] for r in chunk]),
        }
        result.append(avg)
    return result


def _avg(vals: list[float | None]) -> float | None:
    clean = [v for v in vals if v is not None]
    if not clean:
        return None
    return round(sum(clean) / len(clean), 1)


def get_history(period: str = "1h", max_points: int = MAX_POINTS) -> list[dict[str, Any]]:
    """period: 1h, 6h, 24h, 7d. Returns at most max_points downsampled."""
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
    raw = [
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
    return _downsample(raw, max_points)
