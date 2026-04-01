from __future__ import annotations

from abc import ABC, abstractmethod

from app.providers.types import ProviderRequest, ProviderResponse


class Provider(ABC):
    @abstractmethod
    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        raise NotImplementedError
