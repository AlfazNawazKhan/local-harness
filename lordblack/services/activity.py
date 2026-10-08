"""In-memory ring buffer of harness log lines, streamed to the AI Activity
panel's raw console over SSE (§11). Deliberately tiny — no disk journaling on
a 4 GB machine unless the user turns it on in Settings → System & Logs."""
from __future__ import annotations

import asyncio
import collections
import json
import time

_MAX = 500
_buf: collections.deque[dict] = collections.deque(maxlen=_MAX)
_subscribers: set[asyncio.Queue] = set()


def log(step: str, status: str, detail: str = "", ms: int = 0) -> dict:
    ev = {"ts": time.time(), "step": step, "status": status, "detail": detail[:400], "ms": ms}
    _buf.append(ev)
    for q in list(_subscribers):
        if q.full():
            continue
        q.put_nowait(ev)
    return ev


def recent(limit: int = 100) -> list[dict]:
    return list(_buf)[-limit:]


class subscribe:
    """async context manager yielding an SSE-friendly queue of log events."""

    def __init__(self):
        self.q: asyncio.Queue = asyncio.Queue(maxsize=200)

    async def __aenter__(self):
        _subscribers.add(self.q)
        return self.q

    async def __aexit__(self, *exc):
        _subscribers.discard(self.q)


async def stream():
    """Async generator of newline-delimited JSON for SSE."""
    async with subscribe() as q:
        while True:
            ev = await q.get()
            yield json.dumps(ev) + "\n"
