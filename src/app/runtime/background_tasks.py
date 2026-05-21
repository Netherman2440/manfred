from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any


class BackgroundTaskRegistry:
    """Holds strong references to fire-and-forget asyncio tasks.

    asyncio only weakly references tasks; without a strong reference they can
    be GC'd mid-flight. Singleton instance owned by the DI container so tasks
    spawned from per-request services survive past request close().
    """

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()

    def schedule(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def pending_count(self) -> int:
        return sum(1 for task in self._tasks if not task.done())
