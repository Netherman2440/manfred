from __future__ import annotations

from app.domain import Item
from app.services.memory.message_formatter import format_items_for_memory
from app.services.tiktokenizer import BaseTiktokenizer


class MemoryTokenCounter:
    """Counts tokens of items that would be passed to the observer prompt.

    Uses the same formatting as the observer so the threshold reflects the
    actual prompt size, not raw concatenated content.
    """

    def __init__(self, tokenizer: BaseTiktokenizer) -> None:
        self._tokenizer = tokenizer

    def count_items(self, items: list[Item]) -> int:
        if not items:
            return 0
        formatted = format_items_for_memory(items)
        return self._tokenizer.count_tokens_sync(formatted).tokens

    def count_text(self, text: str) -> int:
        if not text:
            return 0
        return self._tokenizer.count_tokens_sync(text).tokens
