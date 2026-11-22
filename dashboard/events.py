"""Event bus: any thread (sim, extensions) sends events; every open browser tab receives them over WebSocket.

Event format (JSON): {"type": "run.ended", "data": {...}, "t": 1732190000.12}
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque

import numpy as np


def _jsonable(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, np.bool_):
        return bool(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


class EventBus:
    """Sends events from any thread to every open browser tab (WebSocket /ws); keeps recent ones for new tabs."""

    def __init__(self, history: int = 200):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: set[asyncio.Queue] = set()
        self._lock = threading.Lock()
        self.history = deque(maxlen=history)  # recent events (not the high-frequency ones), replayed to newly connected tabs

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def emit(self, type: str, data=None, *, keep: bool = True) -> None:
        """Thread-safe. `keep=False` for high-frequency events (e.g. sim.state) that should not go into the history."""
        message = json.dumps({"type": type, "data": data, "t": time.time()}, default=_jsonable)
        if keep:
            self.history.append(message)
        if self._loop is None:
            return
        with self._lock:
            clients = list(self._clients)
        for queue in clients:
            self._loop.call_soon_threadsafe(self._offer, queue, message)

    @staticmethod
    def _offer(queue: asyncio.Queue, message: str) -> None:
        if queue.full():  # slow client: drop the oldest message instead of blocking
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(message)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        with self._lock:
            self._clients.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._clients.discard(queue)

    def log(self, message: str, level: str = "info", source: str = "core") -> None:
        self.emit("log", {"level": level, "message": message, "source": source})
