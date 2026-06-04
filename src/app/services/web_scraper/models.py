from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScrapeResult:
    final_url: str
    markdown: str
    byte_count: int
    status_code: int | None = None
    html: str | None = None


class WebScraperError(Exception):
    pass
