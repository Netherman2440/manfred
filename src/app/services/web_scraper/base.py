from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.web_scraper.models import ScrapeResult


class BaseWebScraperService(ABC):
    @abstractmethod
    async def scrape(self, url: str) -> ScrapeResult: ...
