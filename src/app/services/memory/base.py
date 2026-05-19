from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain import Item
from app.services.memory.models import ObservationResult


class BaseMemoryService(ABC):
    @abstractmethod
    async def observe(
        self,
        *,
        existing_observations: str | None,
        items: list[Item],
    ) -> ObservationResult: ...

    @abstractmethod
    async def reflect(self, observations: str) -> str: ...
