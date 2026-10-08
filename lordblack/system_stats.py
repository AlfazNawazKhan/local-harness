"""Live system stats for the bottom status bar (§4: no polling-heavy JS).

The frontend subscribes to /api/stats/stream (SSE); this module samples CPU /
RAM / VRAM at a throttled interval *on the server* and pushes deltas, so the
browser never has to hammer the API with setInterval fetches.

VRAM is best-effort: we shell out to nvidia-smi if it exists (non-blocking,
cached, never on the hot path). On i3/integrated-GPU laptops there simply is
no VRAM, so the field reports null and the UI shows "—".
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time

try:  # optional; pure-stdlib fallback keeps low-end installs light
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None

_INTERVAL = 1.5          # seconds between samples
_vram_cache: dict = {"ts": 0.0, "value": None}


def _read_proc_stat() -> tuple[float, float] | None:
    """Aggregate CPU jiffies from /proc/stat (Linux/macOS-ish)."""
    try:
        with open("/proc/stat", "r") as f:
            parts = f.readline().split()
        idle = float(int(parts[4]) + int(parts[5]))
        total = float(sum(int(x) for x in parts[1:]))
        return idle, total
    except Exception:
        return None


_prev_cpu: tuple[float, float] | None = None


def cpu_percent() -> float | None:
    if psutil:
        try:
            return round(psutil.cpu_percent(interval=None), 1)
        except Exception:
            pass
    global _prev_cpu
    cur = _read_proc_stat()
    if not cur:
        return None
    if _prev_cpu:
        di = cur[0] - _prev_cpu[0]
        dt = cur[1] - _prev_cpu[1]
        _prev_cpu = cur
        if dt > 0:
            return round(max(0.0, min(100.0, 100.0 * (1 - di / dt))), 1)
    _prev_cpu = cur
    return None


def memory_info() -> dict:
    if psutil:
        m = psutil.virtual_memory()
        return {"ram_used_mb": round(m.used / 1e6), "ram_total_mb": round(m.total / 1e6),
                "ram_percent": m.percent, "swap_used_mb": round(psutil.swap_memory().used / 1e6)}
    # stdlib fallback: /proc/meminfo
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.strip().split()[0])  # kB
        total = info.get("MemTotal", 0) / 1024
        avail = info.get("MemAvailable", 0) / 1024
        used = total - avail
        return {"ram_used_mb": round(used), "ram_total_mb": round(total),
                "ram_percent": round(100 * used / total, 1) if total else 0,
                "swap_used_mb": round((info.get("SwapTotal", 0) -
                                       info.get("SwapFree", 0)) / 1024)}
    except Exception:
        return {"ram_used_mb": None, "ram_total_mb": None, "ram_percent": None,
                "swap_used_mb": None}


def vram_info() -> dict | None:
    now = time.time()
    if now - _vram_cache["ts"] < 5:
        return _vram_cache["value"]
    value = None
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2).stdout.strip().splitlines()
            if out:
                u, t = [float(x) for x in out[0].split(",")[:2]]
                value = {"vram_used_mb": int(u), "vram_total_mb": int(t),
                         "vram_percent": round(100 * u / t, 1) if t else None}
        except Exception:
            value = None
    _vram_cache["ts"] = now
    _vram_cache["value"] = value
    return value


def sample() -> dict:
    d = {"ts": time.time(), "cpu_percent": cpu_percent()}
    d.update(memory_info())
    v = vram_info()
    if v:
        d.update(v)
    else:
        d.update({"vram_used_mb": None, "vram_total_mb": None, "vram_percent": None})
    d["load_avg"] = round(os.getloadavg()[0], 2) if hasattr(os, "getloadavg") else None
    return d


async def stream():
    """Async generator of JSON stat samples for SSE."""
    while True:
        yield sample()
        await asyncio.sleep(_INTERVAL)
