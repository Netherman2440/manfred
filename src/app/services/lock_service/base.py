from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod


class BaseLockService(ABC):
    @abstractmethod
    async def get(self, *keys: str) -> asyncio.Lock: ...
