from __future__ import annotations

from math import ceil
from typing import Any

from app.domain.tool import FunctionToolDefinition, Tool, tool_error, tool_ok


TIKTOKENIZER_DEFINITION = FunctionToolDefinition(
    name="tiktokenizer",
    description="Estimate token count as ceil(len(text) / 4).",
    parameters={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text to estimate token count for.",
            },
        },
        "required": ["text"],
        "additionalProperties": False,
    },
)


async def tiktokenizer_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
    del signal

    text = args.get("text")
    if not isinstance(text, str):
        return tool_error(
            "tiktokenizer expects a string argument: 'text'.",
            hint="Podaj pole 'text' jako string.",
            details={"received": {"text": text}, "expected": {"text": "string"}},
        )

    return tool_ok({"token_count": ceil(len(text) / 4) if text else 0})


tiktokenizer_tool = Tool(
    type="sync",
    definition=TIKTOKENIZER_DEFINITION,
    handler=tiktokenizer_handler,
)
