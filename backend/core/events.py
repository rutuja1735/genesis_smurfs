"""Small in-process event fan-out; SQLite remains the replay source of truth."""

from __future__ import annotations

import asyncio
import threading
from collections import defaultdict
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, Any]]]]] = defaultdict(set)
        self._lock = threading.Lock()

    def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        with self._lock:
            self._subscribers[run_id].add((loop, queue))
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers[run_id] = {item for item in self._subscribers[run_id] if item[1] is not queue}

    def publish(self, run_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers.get(run_id, ()))
        for loop, queue in subscribers:
            if not loop.is_closed():
                loop.call_soon_threadsafe(queue.put_nowait, event)
