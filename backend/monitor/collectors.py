"""
System metrics collectors for RPi5 / Linux.
Uses /proc, /sys, and vcgencmd (when on Raspberry Pi) for minimal dependencies.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

# Paths
PROC_STAT = "/proc/stat"
PROC_MEMINFO = "/proc/meminfo"
PROC_UPTIME = "/proc/uptime"
PROC_NET_DEV = "/proc/net/dev"
PROC_LOADAVG = "/proc/loadavg"
SYS_THERMAL = Path("/sys/class/thermal")
SYS_HWMON = Path("/sys/class/hwmon")
SYS_BLOCK = Path("/sys/block")
VCMEM = "/usr/bin/vcgencmd"  # Raspberry Pi only


def _read_file(path: str | Path, default: str = "") -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except (OSError, FileNotFoundError):
        return default


def _vcgencmd(args: list[str]) -> str:
    if not os.path.isfile(VCMEM):
        return ""
    try:
        r = subprocess.run(
            [VCMEM] + args,
            capture_output=True,
            text=True,
            timeout=2,
        )
        return (r.stdout or "").strip() if r.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


# --- CPU ---


def get_cpu_usage() -> dict[str, Any]:
    """CPU usage from /proc/stat (aggregate and per-core if needed)."""
    raw = _read_file(PROC_STAT)
    if not raw:
        return {"usage_percent": 0.0, "cores": 0}

    lines = [l for l in raw.split("\n") if l.startswith("cpu")]
    total = 0
    idle = 0
    for line in lines:
        parts = line.split()
        if len(parts) >= 5:
            # user, nice, system, idle, iowait, irq, softirq, steal, guest, guest_nice
            total += sum(int(x) for x in parts[1:])
            idle += int(parts[4])
    if total == 0:
        return {"usage_percent": 0.0, "cores": max(1, len(lines) - 1)}
    usage = 100.0 * (1 - idle / total) if total else 0.0
    return {"usage_percent": round(usage, 1), "cores": max(1, len(lines) - 1)}


def get_load_average() -> dict[str, float]:
    raw = _read_file(PROC_LOADAVG)
    if not raw:
        return {"load_1": 0, "load_5": 0, "load_15": 0}
    parts = raw.split()[:3]
    return {
        "load_1": float(parts[0]) if len(parts) > 0 else 0,
        "load_5": float(parts[1]) if len(parts) > 1 else 0,
        "load_15": float(parts[2]) if len(parts) > 2 else 0,
    }


# --- Memory ---


def get_memory() -> dict[str, Any]:
    raw = _read_file(PROC_MEMINFO)
    if not raw:
        return {"total_mb": 0, "used_mb": 0, "free_mb": 0, "usage_percent": 0}

    data = {}
    for line in raw.split("\n"):
        if ":" in line:
            key, val = line.split(":", 1)
            data[key.strip()] = int(val.strip().split()[0])

    total = data.get("MemTotal", 0)
    available = data.get("MemAvailable", data.get("MemFree", 0))
    used = total - available
    total_mb = total // 1024
    used_mb = used // 1024
    free_mb = available // 1024
    usage = 100.0 * used / total if total else 0

    return {
        "total_mb": total_mb,
        "used_mb": used_mb,
        "free_mb": free_mb,
        "usage_percent": round(usage, 1),
    }


# --- Uptime ---


def get_uptime() -> dict[str, Any]:
    raw = _read_file(PROC_UPTIME)
    if not raw:
        return {"seconds": 0, "formatted": "0s"}
    parts = raw.split()
    sec = float(parts[0]) if parts else 0
    days = int(sec // 86400)
    hours = int((sec % 86400) // 3600)
    mins = int((sec % 3600) // 60)
    if days > 0:
        fmt = f"{days}d {hours}h {mins}m"
    elif hours > 0:
        fmt = f"{hours}h {mins}m"
    else:
        fmt = f"{mins}m"
    return {"seconds": int(sec), "formatted": fmt}


# --- Temperature (RPi + generic thermal) ---


def get_temperatures() -> dict[str, Any]:
    result = {"cpu": None, "pmic": None, "rp1": None, "sources": []}

    # vcgencmd (Raspberry Pi)
    vc_temp = _vcgencmd(["measure_temp"])
    if vc_temp:
        m = re.search(r"temp=([\d.]+)'C", vc_temp)
        if m:
            result["cpu"] = round(float(m.group(1)), 1)
            result["sources"].append("vcgencmd")

    vc_pmic = _vcgencmd(["measure_temp", "pmic"])
    if vc_pmic:
        m = re.search(r"temp=([\d.]+)'C", vc_pmic)
        if m:
            result["pmic"] = round(float(m.group(1)), 1)
            result["sources"].append("vcgencmd_pmic")

    # Thermal zones (generic Linux + RPi5)
    if SYS_THERMAL.exists():
        for tz in SYS_THERMAL.iterdir():
            if not tz.name.startswith("thermal_zone"):
                continue
            temp_path = tz / "temp"
            type_path = tz / "type"
            if temp_path.exists():
                try:
                    val = int(_read_file(temp_path)) / 1000.0
                    name = _read_file(type_path) or tz.name
                    result["sources"].append(name)
                    if "cpu" in name.lower() or "soc" in name.lower():
                        if result["cpu"] is None:
                            result["cpu"] = round(val, 1)
                    elif "rp1" in name.lower():
                        result["rp1"] = round(val, 1)
                except (ValueError, OSError):
                    pass

    # hwmon (e.g. rp1_adc on RPi5 for RP1 temp)
    if SYS_HWMON.exists() and result.get("rp1") is None:
        for hw in SYS_HWMON.iterdir():
            name_path = hw / "name"
            name = _read_file(name_path)
            if "rp1" in (name or "").lower():
                for f in hw.iterdir():
                    if f.name.startswith("temp") and f.name.endswith("_input"):
                        try:
                            result["rp1"] = round(int(_read_file(f)) / 1000.0, 1)
                            result["sources"].append("hwmon_rp1")
                            break
                        except (ValueError, OSError):
                            pass
                    break
            break

    return result


# --- Disk ---


def get_disk() -> dict[str, Any]:
    """Root filesystem usage (or first mounted disk)."""
    try:
        stat = os.statvfs("/")
        total = stat.f_blocks * stat.f_frsize
        free = stat.f_bavail * stat.f_frsize
        used = total - free
        total_gb = total / (1024**3)
        used_gb = used / (1024**3)
        free_gb = free / (1024**3)
        usage = 100.0 * used / total if total else 0
        return {
            "total_gb": round(total_gb, 2),
            "used_gb": round(used_gb, 2),
            "free_gb": round(free_gb, 2),
            "usage_percent": round(usage, 1),
            "mount": "/",
        }
    except OSError:
        return {
            "total_gb": 0,
            "used_gb": 0,
            "free_gb": 0,
            "usage_percent": 0,
            "mount": "/",
        }


# --- Network ---


def get_network() -> dict[str, Any]:
    raw = _read_file(PROC_NET_DEV)
    if not raw:
        return {"interfaces": [], "rx_bytes": 0, "tx_bytes": 0}

    lines = raw.strip().split("\n")[2:]  # skip header
    total_rx = 0
    total_tx = 0
    interfaces = []
    for line in lines:
        parts = line.split()
        if len(parts) < 10:
            continue
        name = parts[0].rstrip(":")
        if name in ("lo",):
            continue
        rx = int(parts[1])
        tx = int(parts[9])
        total_rx += rx
        total_tx += tx
        interfaces.append({"name": name, "rx_bytes": rx, "tx_bytes": tx})

    return {
        "interfaces": interfaces,
        "rx_bytes": total_rx,
        "tx_bytes": total_tx,
    }


# --- Static / host info ---


def get_static_info() -> dict[str, Any]:
    hostname = _read_file("/etc/hostname") or _read_file("/proc/sys/kernel/hostname") or "unknown"
    try:
        uname = os.uname()
        system = f"{uname.sysname} {uname.release} {uname.machine}"
    except Exception:
        system = "unknown"

    model = ""
    if Path("/proc/device-tree/model").exists():
        model = _read_file("/proc/device-tree/model").replace("\x00", "").strip()
    if not model and Path("/sys/firmware/devicetree/base/model").exists():
        model = _read_file("/sys/firmware/devicetree/base/model").replace("\x00", "").strip()

    os_release = get_os_release()
    os_name = os_release.get("PRETTY_NAME") or os_release.get("NAME", "")
    cpu_model = get_cpu_model()

    return {
        "hostname": hostname,
        "system": system,
        "model": model or "Generic Linux",
        "os_release": os_name,
        "cpu_model": cpu_model,
        "os_release_full": os_release,
    }


# --- Processes (top by CPU) ---

PROC_PID = Path("/proc")


def get_top_processes(limit: int = 15) -> list[dict[str, Any]]:
    """Top processes by CPU time (from /proc)."""
    result = []
    if not PROC_PID.exists():
        return result
    for pid_dir in PROC_PID.iterdir():
        if not pid_dir.name.isdigit():
            continue
        try:
            stat_path = pid_dir / "stat"
            cmdline_path = pid_dir / "cmdline"
            status_path = pid_dir / "status"
            if not stat_path.exists():
                continue
            raw = _read_file(stat_path)
            if not raw:
                continue
            # pid ( comm ) state ppid ... utime stime
            rparen = raw.rfind(")")
            if rparen < 0:
                continue
            rest = raw[rparen + 2:].split()
            if len(rest) < 14:
                continue
            comm = raw[raw.find("(") + 1 : rparen].strip() or "?"
            utime = int(rest[11])
            stime = int(rest[12])
            cpu_time = utime + stime
            rss = 0
            if status_path.exists():
                status_raw = _read_file(status_path)
                for line in status_raw.split("\n"):
                    if line.startswith("VmRSS:"):
                        rss = int(line.split()[1])
                        break
            cmdline = _read_file(cmdline_path).replace("\x00", " ").strip() or comm
            name = cmdline.split()[0] if cmdline else comm
            if len(name) > 50:
                name = name[:47] + "..."
            result.append({
                "pid": int(pid_dir.name),
                "name": name,
                "comm": comm,
                "cpu_time": cpu_time,
                "rss_kb": rss,
            })
        except (ValueError, OSError, IndexError):
            continue
    result.sort(key=lambda x: x["cpu_time"], reverse=True)
    return result[:limit]


# --- Disk I/O ---

PROC_DISKSTATS = "/proc/diskstats"


def get_disk_io() -> dict[str, Any]:
    """Disk I/O from /proc/diskstats (reads/writes in sectors)."""
    raw = _read_file(PROC_DISKSTATS)
    if not raw:
        return {"read_sectors": 0, "write_sectors": 0, "devices": []}
    total_read = 0
    total_write = 0
    devices = []
    for line in raw.strip().split("\n"):
        parts = line.split()
        if len(parts) < 14:
            continue
        name = parts[2]
        if name.startswith("loop") or name.startswith("ram"):
            continue
        read_sectors = int(parts[5])
        write_sectors = int(parts[9])
        total_read += read_sectors
        total_write += write_sectors
        devices.append({"name": name, "read_sectors": read_sectors, "write_sectors": write_sectors})
    return {
        "read_sectors": total_read,
        "write_sectors": total_write,
        "read_mb": round(total_read * 512 / (1024 * 1024), 2),
        "write_mb": round(total_write * 512 / (1024 * 1024), 2),
        "devices": devices[:10],
    }


# --- Swap ---


def get_swap() -> dict[str, Any]:
    raw = _read_file(PROC_MEMINFO)
    if not raw:
        return {"total_mb": 0, "used_mb": 0, "free_mb": 0, "usage_percent": 0}
    data = {}
    for line in raw.split("\n"):
        if ":" in line:
            key, val = line.split(":", 1)
            data[key.strip()] = int(val.strip().split()[0])
    total = data.get("SwapTotal", 0)
    free = data.get("SwapFree", 0)
    used = total - free
    total_mb = total // 1024
    used_mb = used // 1024
    free_mb = free // 1024
    usage = 100.0 * used / total if total else 0
    return {
        "total_mb": total_mb,
        "used_mb": used_mb,
        "free_mb": free_mb,
        "usage_percent": round(usage, 1),
    }


# --- OS release ---


def get_os_release() -> dict[str, str]:
    data = {}
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        raw = _read_file(path)
        if not raw:
            continue
        for line in raw.split("\n"):
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip().strip('"')
        if data:
            break
    return data


# --- CPU model ---


def get_cpu_model() -> str:
    raw = _read_file("/proc/cpuinfo")
    if not raw:
        return ""
    for line in raw.split("\n"):
        if "model name" in line.lower() or "Model" in line:
            if ":" in line:
                return line.split(":", 1)[1].strip()
    if "Hardware" in raw:
        for line in raw.split("\n"):
            if line.strip().startswith("Hardware"):
                if ":" in line:
                    return line.split(":", 1)[1].strip()
    return ""


# --- Voltage (vcgencmd, RPi) ---


def get_voltage() -> dict[str, Any]:
    result = {}
    out = _vcgencmd(["measure_volts", "core"])
    if out:
        m = re.search(r"volt=([\d.]+)V", out)
        if m:
            result["core"] = round(float(m.group(1)), 2)
    for name in ("sdram_c", "sdram_i", "sdram_p"):
        out = _vcgencmd(["measure_volts", name])
        if out:
            m = re.search(r"volt=([\d.]+)V", out)
            if m:
                result[name] = round(float(m.group(1)), 2)
    return result


# --- Aggregate dynamic (live) data ---


def collect_dynamic() -> dict[str, Any]:
    return {
        "cpu": get_cpu_usage(),
        "load": get_load_average(),
        "memory": get_memory(),
        "swap": get_swap(),
        "uptime": get_uptime(),
        "temperature": get_temperatures(),
        "disk": get_disk(),
        "disk_io": get_disk_io(),
        "network": get_network(),
        "voltage": get_voltage(),
        "processes": get_top_processes(15),
        "timestamp": time.time(),
    }


def collect_static() -> dict[str, Any]:
    return get_static_info()
