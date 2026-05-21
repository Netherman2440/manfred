from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.tiktokenizer.models import TokenCount


class BaseTiktokenizer(ABC):
    @abstractmethod
    def count_tokens_sync(self, text: str, model: str | None = None) -> TokenCount: ...

    @abstractmethod
    async def count_tokens(self, text: str, model: str | None = None) -> TokenCount: ...
