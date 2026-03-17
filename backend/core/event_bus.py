from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, DefaultDict


@dataclass(frozen=True)
class Event:
    topic: str
    ts: float
    payload: dict[str, Any]


AsyncHandler = Callable[[Event], Awaitable[None]]
SyncHandler = Callable[[Event], None]


class EventBus:
    """
    Very small in-process pub/sub.

    - Topics are arbitrary strings (e.g. "metrics", "alerts", "autodarts:event").
    - Subscribers can be sync or async callables.
    - Publishing is fire-and-forget; handlers are isolated (exceptions swallowed).
    """

    def __init__(self) -> None:
        self._async_handlers: DefaultDict[str, list[AsyncHandler]] = defaultdict(list)
        self._sync_handlers: DefaultDict[str, list[SyncHandler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: SyncHandler | AsyncHandler) -> None:
        if asyncio.iscoroutinefunction(handler):
            self._async_handlers[topic].append(handler)  # type: ignore[arg-type]
        else:
            self._sync_handlers[topic].append(handler)  # type: ignore[arg-type]

    def unsubscribe_all(self, topic: str) -> None:
        self._async_handlers.pop(topic, None)
        self._sync_handlers.pop(topic, None)

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        ev = Event(topic=topic, ts=time.time(), payload=payload)
        for h in list(self._sync_handlers.get(topic, [])):
            try:
                h(ev)
            except Exception:
                pass
        for h in list(self._async_handlers.get(topic, [])):
            try:
                asyncio.create_task(h(ev))
            except Exception:
                pass

