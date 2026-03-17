from __future__ import annotations

import time
from typing import Any, Literal

from monitor.history import _get_conn  # reuse same SQLite db


Metric = Literal["cpu", "mem", "swap", "disk", "temp_cpu", "temp_pmic", "temp_rp1"]


def _period_range(period: str) -> tuple[float, float]:
    now = time.time()
    lt = time.localtime(now)
    # midnight local
    start_today = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, lt.tm_wday, lt.tm_yday, lt.tm_isdst))
    if period == "today":
        return start_today, now
    if period == "yesterday":
        return start_today - 86400, start_today
    if period == "week":
        return now - 7 * 86400, now
    if period == "month":
        return now - 30 * 86400, now
    # default: last 24h
    return now - 86400, now


def bucket_series(metric: Metric, start: float, end: float, bucket_sec: int) -> list[dict[str, Any]]:
    """
    Returns buckets with avg/min/max for a metric.
    """
    bucket_sec = max(60, int(bucket_sec))
    with _get_conn() as conn:
        cur = conn.execute(
            """
            SELECT
              CAST(ts / ? AS INTEGER) * ? AS b,
              AVG(COALESCE(%s, NULL)) AS avg,
              MIN(COALESCE(%s, NULL)) AS min,
              MAX(COALESCE(%s, NULL)) AS max,
              COUNT(*) AS n
            FROM metrics
            WHERE ts >= ? AND ts < ?
            GROUP BY b
            ORDER BY b
            """
            % (metric, metric, metric),
            (bucket_sec, bucket_sec, start, end),
        )
        rows = cur.fetchall()
    return [{"ts": r["b"], "avg": _round(r["avg"]), "min": _round(r["min"]), "max": _round(r["max"]), "n": r["n"]} for r in rows]


def compare(metric: Metric, period: Literal["today", "yesterday", "week", "month"]) -> dict[str, Any]:
    start, end = _period_range(period)
    if period in ("today", "yesterday"):
        bucket = 300  # 5 min
    elif period == "week":
        bucket = 3600  # 1 h
    else:
        bucket = 3 * 3600  # 3 h
    series = bucket_series(metric=metric, start=start, end=end, bucket_sec=bucket)
    stats = summary_stats(metric=metric, start=start, end=end)
    return {"metric": metric, "period": period, "start": start, "end": end, "bucket_sec": bucket, "series": series, "summary": stats}


def summary_stats(metric: Metric, start: float, end: float) -> dict[str, Any]:
    with _get_conn() as conn:
        cur = conn.execute(
            f"SELECT AVG({metric}) AS avg, MIN({metric}) AS min, MAX({metric}) AS max, COUNT(*) AS n FROM metrics WHERE ts >= ? AND ts < ?",
            (start, end),
        )
        r = cur.fetchone()
    return {"avg": _round(r["avg"]), "min": _round(r["min"]), "max": _round(r["max"]), "n": int(r["n"] or 0)}


def trend(metric: Metric, window_min: int = 30) -> dict[str, Any]:
    """
    Simple slope estimation over the last window (minutes) using two-point delta.
    """
    now = time.time()
    start = now - max(5, int(window_min)) * 60
    with _get_conn() as conn:
        cur = conn.execute(
            f"SELECT ts, {metric} AS v FROM metrics WHERE ts >= ? AND {metric} IS NOT NULL ORDER BY ts",
            (start,),
        )
        rows = cur.fetchall()
    if len(rows) < 2:
        return {"metric": metric, "window_min": window_min, "slope_per_min": None, "direction": "flat"}
    first = rows[0]
    last = rows[-1]
    dt_min = max(1e-6, (last["ts"] - first["ts"]) / 60.0)
    dv = (last["v"] - first["v"]) if (last["v"] is not None and first["v"] is not None) else 0
    slope = dv / dt_min
    direction = "up" if slope > 0.05 else "down" if slope < -0.05 else "flat"
    return {"metric": metric, "window_min": window_min, "slope_per_min": _round(slope, 3), "direction": direction}


def predict_time_to_threshold(metric: Metric, threshold: float, window_min: int = 60) -> dict[str, Any]:
    """
    Heuristic prediction: if trend slope indicates increase, estimate time to reach threshold.
    """
    tr = trend(metric=metric, window_min=window_min)
    slope = tr.get("slope_per_min")
    if slope is None or slope <= 0:
        return {"metric": metric, "threshold": threshold, "window_min": window_min, "time_to_threshold_sec": None, "confidence": 0.2, "trend": tr}

    now = time.time()
    with _get_conn() as conn:
        cur = conn.execute(
            f"SELECT {metric} AS v FROM metrics WHERE ts <= ? AND {metric} IS NOT NULL ORDER BY ts DESC LIMIT 1",
            (now,),
        )
        r = cur.fetchone()
    if not r or r["v"] is None:
        return {"metric": metric, "threshold": threshold, "window_min": window_min, "time_to_threshold_sec": None, "confidence": 0.2, "trend": tr}
    current = float(r["v"])
    if current >= threshold:
        return {"metric": metric, "threshold": threshold, "window_min": window_min, "time_to_threshold_sec": 0, "confidence": 0.6, "trend": tr}
    mins = (threshold - current) / float(slope)
    sec = max(0, int(mins * 60))
    confidence = 0.35 if mins > 240 else 0.55 if mins > 60 else 0.75
    return {"metric": metric, "threshold": threshold, "window_min": window_min, "time_to_threshold_sec": sec, "confidence": confidence, "trend": tr}


def _round(v: Any, digits: int = 2) -> float | None:
    try:
        if v is None:
            return None
        return round(float(v), digits)
    except Exception:
        return None

