from __future__ import annotations

import asyncio
from typing import Any

from app.domain.tool import FunctionToolDefinition, Tool


WAIT_DEFINITION = FunctionToolDefinition(
    name="wait",
    description=(
        "Wait for a specific number of seconds.  After the wait finishes, "
        "immediately perform the stated next_task."
    ),
    parameters={
        "type": "object",
        "properties": {
            "time": {
                "type": "number",
                "description": "How many seconds to wait before returning control to the model.",
            },
            "next_task": {
                "type": "string",
                "description": "What the model should do after the waiting period ends.",
            },
        },
        "required": ["time", "next_task"],
        "additionalProperties": False,
    },
)


async def wait_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
    del signal

    wait_time = args.get("time")
    if isinstance(wait_time, bool) or not isinstance(wait_time, int | float):
        raise ValueError("wait expects a numeric argument: 'time'.")
    if wait_time < 0:
        raise ValueError("wait expects 'time' to be greater than or equal to 0.")

    next_task = args.get("next_task")
    if not isinstance(next_task, str) or next_task.strip() == "":
        raise ValueError("wait expects a non-empty string argument: 'next_task'.")

    await asyncio.sleep(wait_time)
    return {
        "ok": True,
        "output": f"Wiat time's up Your next action should be: {next_task.strip()}",
    }


wait_tool = Tool(
    type="sync",
    definition=WAIT_DEFINITION,
    handler=wait_handler,
)
