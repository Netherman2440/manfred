from __future__ import annotations

from typing import Any

from app.domain.tool import FunctionToolDefinition, Tool


def _require_non_empty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{name}' must be a non-empty string")
    return value.strip()


async def handle_ask_user(args: dict[str, Any], signal: Any | None = None) -> dict[str, bool | str]:
    del signal
    question = _require_non_empty_string(args.get("question"), "question")
    return {"ok": True, "output": question}


ask_user_tool = Tool(
    type="human",
    definition=FunctionToolDefinition(
        name="ask_user",
        description="Ask the user for missing information and pause execution until a reply is delivered.",
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question that should be shown to the user.",
                },
            },
            "required": ["question"],
            "additionalProperties": False,
        },
    ),
    handler=handle_ask_user,
)
