from __future__ import annotations

from typing import Any

from app.domain.tool import FunctionToolDefinition, Tool, ToolExecutionContext
from app.utils.string_validator import _require_non_empty_string


async def handle_message(args: dict[str, Any], context: ToolExecutionContext) -> dict[str, bool | str]:
    del context
    text = _require_non_empty_string(args.get("text"), "text")
    return {"ok": True, "output": text}


message_tool = Tool(
    type="human",
    definition=FunctionToolDefinition(
        name="message",
        description=(
            "Send a message to your parent agent (the one that delegated this task to you). "
            "Use when you need clarification, missing context, or are stuck. Your message "
            "bubbles up the delegation chain — your parent may answer directly or forward to "
            "the operator. Your turn pauses until a reply is delivered."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": (
                        "The message for your parent agent. Be specific: what you tried, what "
                        "you found, what you need, and your hypothesis if any."
                    ),
                },
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    ),
    handler=handle_message,
)
