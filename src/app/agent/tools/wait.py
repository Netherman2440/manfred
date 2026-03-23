from __future__ import annotations

import asyncio
from typing import Any

from app.domain.tool import FunctionToolDefinition, Tool, tool_error, tool_ok


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
        return tool_error(
            "wait expects a numeric argument: 'time'.",
            hint="Podaj pole 'time' jako number >= 0, np. 5.",
            details={
                "received": {"time": wait_time},
                "expected": {"time": "number >= 0"},
            },
        )
    if wait_time < 0:
        return tool_error(
            "wait expects 'time' to be greater than or equal to 0.",
            hint="Podaj pole 'time' jako liczbę sekund większą lub równą 0.",
            details={
                "received": {"time": wait_time},
                "expected": {"time": "number >= 0"},
            },
        )

    next_task = args.get("next_task")
    if not isinstance(next_task, str) or next_task.strip() == "":
        return tool_error(
            "wait expects a non-empty string argument: 'next_task'.",
            hint="Podaj pole 'next_task' jako niepusty opis kolejnego kroku.",
            details={
                "received": {"next_task": next_task},
                "expected": {"next_task": "non-empty string"},
            },
        )

    await asyncio.sleep(wait_time)
    return tool_ok(f"Wiat time's up Your next action should be: {next_task.strip()}")


wait_tool = Tool(
    type="sync",
    definition=WAIT_DEFINITION,
    handler=wait_handler,
)
