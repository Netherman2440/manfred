from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx


logger = logging.getLogger("app.services.model_catalog_service")


class ModelCatalogUnavailable(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ModelSummary:
    id: str
    name: str
    context_length: int | None
    pricing_prompt_per_1k: float | None
    pricing_completion_per_1k: float | None


class ModelCatalogService:
    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        api_url: str,
        api_key: str,
        cache_ttl_seconds: int = 3600,
    ) -> None:
        self._http_client = http_client
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache: tuple[float, list[ModelSummary]] | None = None
        self._lock = asyncio.Lock()

    async def list_models(self) -> list[ModelSummary]:
        """Return cached model list. Fetches from OpenRouter on cache miss.

        Raises ModelCatalogUnavailable if OpenRouter is unreachable and cache is empty.
        """
        now = time.monotonic()
        if self._cache is not None:
            cached_at, cached_models = self._cache
            if now - cached_at < self._cache_ttl_seconds:
                return cached_models

        async with self._lock:
            # Re-check after acquiring lock (another coroutine may have refreshed)
            now = time.monotonic()
            if self._cache is not None:
                cached_at, cached_models = self._cache
                if now - cached_at < self._cache_ttl_seconds:
                    return cached_models

            try:
                models = await self._fetch_models()
                self._cache = (time.monotonic(), models)
                return models
            except Exception as exc:
                logger.warning("Failed to fetch models from OpenRouter: %s", exc)
                if self._cache is not None:
                    _, stale_models = self._cache
                    return stale_models
                raise ModelCatalogUnavailable("Unable to fetch model list from OpenRouter.") from exc

    async def _fetch_models(self) -> list[ModelSummary]:
        url = f"{self._api_url}/models"
        response = await self._http_client.get(
            url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=15.0,
        )
        response.raise_for_status()
        data = response.json()

        raw_models = data.get("data", []) if isinstance(data, dict) else []
        models: list[ModelSummary] = []
        for raw in raw_models:
            if not isinstance(raw, dict):
                continue
            model_id = raw.get("id")
            if not model_id:
                continue

            name = raw.get("name") or model_id
            context_length = raw.get("context_length")
            try:
                context_length = int(context_length) if isinstance(context_length, (int, float, str)) else None
            except (ValueError, TypeError):
                context_length = None

            pricing = raw.get("pricing") or {}
            pricing_prompt = self._parse_price(pricing.get("prompt"))
            pricing_completion = self._parse_price(pricing.get("completion"))

            models.append(
                ModelSummary(
                    id=str(model_id),
                    name=str(name),
                    context_length=context_length,
                    pricing_prompt_per_1k=pricing_prompt,
                    pricing_completion_per_1k=pricing_completion,
                )
            )

        models.sort(key=lambda m: m.id)
        return models

    @staticmethod
    def _parse_price(raw: object) -> float | None:
        if raw is None:
            return None
        try:
            per_token = float(str(raw))
            return per_token * 1000
        except (ValueError, TypeError):
            return None
