from __future__ import annotations

from typing import Any

from app.domain.tool import FunctionToolDefinition, Tool, tool_error, tool_ok


SEND_MESSAGE_DEFINITION = FunctionToolDefinition(
    name="send_message",
    description="Store a system message in another agent's history without waking it up.",
    parameters={
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "Target agent id.",
            },
            "message": {
                "type": "string",
                "description": "Message content to persist for the target agent.",
            },
        },
        "required": ["to", "message"],
        "additionalProperties": False,
    },
)


async def send_message_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
    del signal

    target_agent_id = args.get("to")
    message = args.get("message")
    if not isinstance(target_agent_id, str) or target_agent_id.strip() == "":
        return tool_error(
            "send_message expects a non-empty string argument: 'to'.",
            hint="Podaj identyfikator docelowego agenta.",
            details={"received": {"to": target_agent_id}},
        )
    if not isinstance(message, str) or message.strip() == "":
        return tool_error(
            "send_message expects a non-empty string argument: 'message'.",
            hint="Podaj treść wiadomości dla docelowego agenta.",
            details={"received": {"message": message}},
        )

    return tool_ok(
        {
            "to": target_agent_id.strip(),
            "message": message.strip(),
        }
    )


send_message_tool = Tool(
    type="sync",
    definition=SEND_MESSAGE_DEFINITION,
    handler=send_message_handler,
)
