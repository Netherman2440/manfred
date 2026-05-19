from datetime import UTC, datetime

from app.domain import Item, ItemType, MessageRole
from app.services.memory.message_formatter import format_items_for_memory


def _msg(role: MessageRole, content: str, *, sequence: int = 1) -> Item:
    return Item(
        id=f"item-{sequence}",
        session_id="s1",
        agent_id="a1",
        sequence=sequence,
        type=ItemType.MESSAGE,
        role=role,
        content=content,
        call_id=None,
        name=None,
        arguments_json=None,
        output=None,
        is_error=False,
        created_at=datetime(2026, 5, 15, 14, 30, tzinfo=UTC),
    )


def _function_call(name: str, arguments_json: str, *, sequence: int = 2) -> Item:
    return Item(
        id=f"call-{sequence}",
        session_id="s1",
        agent_id="a1",
        sequence=sequence,
        type=ItemType.FUNCTION_CALL,
        role=MessageRole.ASSISTANT,
        content=None,
        call_id="call-1",
        name=name,
        arguments_json=arguments_json,
        output=None,
        is_error=False,
        created_at=datetime(2026, 5, 15, 14, 31, tzinfo=UTC),
    )


def _function_output(name: str, output: str, *, sequence: int = 3) -> Item:
    return Item(
        id=f"out-{sequence}",
        session_id="s1",
        agent_id="a1",
        sequence=sequence,
        type=ItemType.FUNCTION_CALL_OUTPUT,
        role=MessageRole.ASSISTANT,
        content=None,
        call_id="call-1",
        name=name,
        arguments_json=None,
        output=output,
        is_error=False,
        created_at=datetime(2026, 5, 15, 14, 32, tzinfo=UTC),
    )


def test_format_user_and_assistant_messages() -> None:
    items = [
        _msg(MessageRole.USER, "Cześć"),
        _msg(MessageRole.ASSISTANT, "Hello", sequence=2),
    ]

    formatted = format_items_for_memory(items)

    assert "User: Cześć" in formatted
    assert "Assistant: Hello" in formatted


def test_format_tool_call_serializes_arguments() -> None:
    items = [_function_call("calculator", '{"x": 1, "y": 2}')]

    formatted = format_items_for_memory(items)

    assert "Tool Call calculator:" in formatted
    assert '"x": 1' in formatted
    assert '"y": 2' in formatted


def test_format_tool_output_includes_name_and_output() -> None:
    items = [_function_output("calculator", "3")]

    formatted = format_items_for_memory(items)

    assert "Tool Result calculator: 3" in formatted
