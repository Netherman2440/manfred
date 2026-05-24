from __future__ import annotations

import logging
from typing import Any

from firecrawl import AsyncFirecrawl

from app.services.web_scraper.base import BaseWebScraperService
from app.services.web_scraper.models import ScrapeResult, WebScraperError

logger = logging.getLogger("app.services.web_scraper.firecrawl")


class FirecrawlScraperService(BaseWebScraperService):
    def __init__(self, *, api_key: str, wait_for_ms: int = 0, only_main_content: bool = True) -> None:
        self._api_key = api_key
        self._wait_for_ms = wait_for_ms
        self._only_main_content = only_main_content
        self._client: AsyncFirecrawl | None = (
            AsyncFirecrawl(api_key=api_key) if api_key else None
        )

    async def scrape(self, url: str) -> ScrapeResult:
        if self._client is None:
            raise WebScraperError(
                "Firecrawl is not configured — set FIRECRAWL_API_KEY in the environment to enable scrape_url"
            )
        try:
            doc = await self._client.scrape(
                url,
                formats=["markdown"],
                only_main_content=self._only_main_content,
                wait_for=self._wait_for_ms,
            )
        except Exception as exc:
            logger.exception("Firecrawl scrape failed for %s", url)
            raise WebScraperError(f"Firecrawl scrape failed: {exc}") from exc

        markdown = _extract(doc, "markdown") or ""
        if not isinstance(markdown, str):
            raise WebScraperError(f"Firecrawl returned non-string markdown for {url}: {type(markdown).__name__}")

        metadata = _extract(doc, "metadata") or {}
        final_url = (
            _meta_get(metadata, "source_url")
            or _meta_get(metadata, "sourceURL")
            or _meta_get(metadata, "url")
            or url
        )
        status_code = _meta_get(metadata, "status_code") or _meta_get(metadata, "statusCode")
        try:
            status_code_int = int(status_code) if status_code is not None else None
        except (TypeError, ValueError):
            status_code_int = None

        return ScrapeResult(
            final_url=str(final_url),
            markdown=markdown,
            byte_count=len(markdown.encode("utf-8")),
            status_code=status_code_int,
        )


def _extract(doc: Any, key: str) -> Any:
    if doc is None:
        return None
    if hasattr(doc, key):
        return getattr(doc, key)
    if isinstance(doc, dict):
        return doc.get(key)
    return None


def _meta_get(metadata: Any, key: str) -> Any:
    if metadata is None:
        return None
    if isinstance(metadata, dict):
        return metadata.get(key)
    return getattr(metadata, key, None)
