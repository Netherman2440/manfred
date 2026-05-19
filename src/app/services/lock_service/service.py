from __future__ import annotations

import asyncio

from app.services.lock_service.base import BaseLockService


class LockService(BaseLockService):
    """Per-key asyncio.Lock registry.

    A single instance lives in the DI container so multiple call sites can
    serialize on the same composite key (e.g. user_id + agent_name).
    """

    def __init__(self) -> None:
        self._locks: dict[tuple[str, ...], asyncio.Lock] = {}
        self._registry_lock = asyncio.Lock()

    async def get(self, *keys: str) -> asyncio.Lock:
        key = tuple(keys)
        async with self._registry_lock:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock
