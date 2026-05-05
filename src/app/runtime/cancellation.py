from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass

from app.runtime.runner_types import RunResult


class CancellationRequestedError(RuntimeError):
    pass


class CancellationSignal:
    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._thread_event = threading.Event()
        try:
            self._loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    @property
    def is_cancelled(self) -> bool:
        return self._thread_event.is_set()

    @property
    def thread_event(self) -> threading.Event:
        return self._thread_event

    def cancel(self) -> None:
        self._thread_event.set()
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._event.set)
            return
        self._event.set()

    async def wait(self) -> None:
        await self._event.wait()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise CancellationRequestedError("Run cancelled.")


@dataclass(slots=True)
class ActiveRunHandle:
    agent_id: str
    signal: CancellationSignal
    completion: asyncio.Future[RunResult]


class ActiveRunRegistry:
    def __init__(self) -> None:
        self._handles: dict[str, ActiveRunHandle] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        agent_id: str,
        *,
        signal: CancellationSignal | None = None,
    ) -> ActiveRunHandle:
        async with self._lock:
            existing = self._handles.get(agent_id)
            if existing is not None:
                raise RuntimeError(f"Run already active for agent: {agent_id}")

            handle = ActiveRunHandle(
                agent_id=agent_id,
                signal=signal or CancellationSignal(),
                completion=asyncio.get_running_loop().create_future(),
            )
            self._handles[agent_id] = handle
            return handle

    async def cancel(self, agent_id: str) -> RunResult | None:
        async with self._lock:
            handle = self._handles.get(agent_id)

        if handle is None:
            return None

        handle.signal.cancel()
        return await handle.completion

    async def finish(self, agent_id: str, result: RunResult) -> None:
        async with self._lock:
            handle = self._handles.pop(agent_id, None)

        if handle is None or handle.completion.done():
            return

        handle.completion.set_result(result)

    def is_active(self, agent_id: str) -> bool:
        return agent_id in self._handles
