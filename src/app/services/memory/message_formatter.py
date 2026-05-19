from __future__ import annotations

import json
from datetime import datetime

from app.domain import Item
from app.domain.types import ItemType, MessageRole


def _timestamp_prefix(created_at: datetime) -> str:
    return created_at.astimezone().strftime("%B %d, %Y %I:%M %p")


def _format_arguments(arguments_json: str | None) -> str:
    if not arguments_json:
        return "{}"
    try:
        parsed = json.loads(arguments_json)
    except json.JSONDecodeError:
        return arguments_json
    return json.dumps(parsed, ensure_ascii=False)


def format_items_for_memory(items: list[Item]) -> str:
    """Format a list of Items as plain text for the observer LLM prompt.

    Mirrors the heyfibo formatter (`User: ...`, `Assistant: ...`,
    `Tool Call name: {...}`, `Tool Result name: ...`) but operates on Manfred's
    Item domain model.
    """
    lines: list[str] = []
    for item in items:
        prefix = f"{_timestamp_prefix(item.created_at)} | "

        if item.type == ItemType.MESSAGE and item.content:
            if item.role == MessageRole.USER:
                lines.append(f"{prefix}User: {item.content}")
            elif item.role == MessageRole.ASSISTANT:
                lines.append(f"{prefix}Assistant: {item.content}")
            elif item.role == MessageRole.SYSTEM:
                lines.append(f"{prefix}System: {item.content}")
            continue

        if item.type == ItemType.FUNCTION_CALL:
            name = item.name or ""
            lines.append(f"{prefix}Tool Call {name}: {_format_arguments(item.arguments_json)}")
            continue

        if item.type == ItemType.FUNCTION_CALL_OUTPUT:
            name = item.name or ""
            output = item.output or ""
            lines.append(f"{prefix}Tool Result {name}: {output}")
            continue

        if item.type == ItemType.REASONING and item.content:
            lines.append(f"{prefix}Reasoning: {item.content}")

    return "\n".join(lines)
