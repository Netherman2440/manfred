from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterable

from app.providers.types import ProviderRequest, ProviderResponse, ProviderStreamEvent


class Provider(ABC):
    @abstractmethod
    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        raise NotImplementedError

    @abstractmethod
    async def stream(self, request: ProviderRequest) -> AsyncIterable[ProviderStreamEvent]:
        raise NotImplementedError
