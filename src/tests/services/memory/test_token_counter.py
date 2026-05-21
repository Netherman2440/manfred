from datetime import UTC, datetime

from app.domain import Item, ItemType, MessageRole
from app.services.memory.token_counter import MemoryTokenCounter
from app.services.tiktokenizer import TiktokenizerService


def _msg(content: str) -> Item:
    return Item(
        id="item-1",
        session_id="s1",
        agent_id="a1",
        sequence=1,
        type=ItemType.MESSAGE,
        role=MessageRole.USER,
        content=content,
        call_id=None,
        name=None,
        arguments_json=None,
        output=None,
        is_error=False,
        created_at=datetime(2026, 5, 15, 14, 30, tzinfo=UTC),
    )


def test_count_items_empty_returns_zero() -> None:
    counter = MemoryTokenCounter(TiktokenizerService())
    assert counter.count_items([]) == 0


def test_count_items_returns_positive_for_real_content() -> None:
    counter = MemoryTokenCounter(TiktokenizerService())
    assert counter.count_items([_msg("hello world")]) > 0


def test_count_text_returns_zero_for_empty() -> None:
    counter = MemoryTokenCounter(TiktokenizerService())
    assert counter.count_text("") == 0


def test_count_text_returns_positive_for_real_content() -> None:
    counter = MemoryTokenCounter(TiktokenizerService())
    assert counter.count_text("hello world") > 0
