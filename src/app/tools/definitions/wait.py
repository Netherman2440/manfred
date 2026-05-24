from __future__ import annotations

import asyncio
from typing import Any

from app.domain.tool import FunctionToolDefinition, Tool, ToolExecutionContext

MAX_WAIT_SECONDS = 600


def _to_seconds(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("'seconds' must be an integer")
    if value <= 0:
        raise ValueError("'seconds' must be a positive integer")
    if value > MAX_WAIT_SECONDS:
        raise ValueError(f"'seconds' must be <= {MAX_WAIT_SECONDS}")
    return value


async def handle_wait(args: dict[str, Any], context: ToolExecutionContext) -> dict[str, bool | str]:
    del context
    seconds = _to_seconds(args.get("seconds"))
    await asyncio.sleep(seconds)
    return {"ok": True, "output": f"Time has passed: waited {seconds} seconds."}


wait_tool = Tool(
    type="sync",
    definition=FunctionToolDefinition(
        name="wait",
        description=(
            "Pause execution for a given number of seconds, then return a message confirming the wait. "
            "Useful for waiting out temporary bans, rate limits, reboots, or rate-limited APIs. "
            f"Maximum wait is {MAX_WAIT_SECONDS} seconds."
        ),
        parameters={
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_WAIT_SECONDS,
                    "description": "Number of seconds to wait before returning control to the agent.",
                },
            },
            "required": ["seconds"],
        },
    ),
    handler=handle_wait,
)
