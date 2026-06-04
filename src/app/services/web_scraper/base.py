from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from app.services.web_scraper.models import ScrapeResult


class BaseWebScraperService(ABC):
    @abstractmethod
    async def scrape(
        self,
        url: str,
        *,
        actions: Sequence[dict[str, Any]] | None = None,
        formats: Sequence[str] = ("markdown",),
        only_main_content: bool | None = None,
        wait_for: int | None = None,
    ) -> ScrapeResult: ...
