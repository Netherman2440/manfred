from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass

import tiktoken

logger = logging.getLogger("app.services.tiktokenizer_service")

DEFAULT_MODEL = "gpt-4o"
FALLBACK_ENCODING = "o200k_base"


@dataclass(frozen=True, slots=True)
class TokenCount:
    model: str
    encoding: str
    tokens: int
    chars: int


class TiktokenizerService:
    def __init__(self, *, default_model: str = DEFAULT_MODEL) -> None:
        self._default_model = default_model
        self._encoding_cache: dict[str, tiktoken.Encoding] = {}
        self._lock = threading.Lock()

    def count_tokens_sync(self, text: str, model: str | None = None) -> TokenCount:
        target_model = (model or self._default_model).strip()
        encoding = self._resolve_encoding(target_model)
        return TokenCount(
            model=target_model,
            encoding=encoding.name,
            tokens=len(encoding.encode(text)),
            chars=len(text),
        )

    async def count_tokens(self, text: str, model: str | None = None) -> TokenCount:
        return await asyncio.to_thread(self.count_tokens_sync, text, model)

    def _resolve_encoding(self, model: str) -> tiktoken.Encoding:
        with self._lock:
            cached = self._encoding_cache.get(model)
            if cached is not None:
                return cached

            try:
                encoding = tiktoken.encoding_for_model(model)
            except KeyError:
                logger.info(
                    "Unknown model for tiktoken (%s); falling back to %s.",
                    model,
                    FALLBACK_ENCODING,
                )
                encoding = tiktoken.get_encoding(FALLBACK_ENCODING)

            self._encoding_cache[model] = encoding
            return encoding
