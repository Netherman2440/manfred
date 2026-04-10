from __future__ import annotations

import json
from typing import Any

from app.domain.tool import FunctionToolDefinition, Tool


def _require_non_empty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{name}' must be a non-empty string")
    return value.strip()


async def handle_delegate(args: dict[str, Any], signal: Any | None = None) -> dict[str, bool | str]:
    del signal
    agent_name = _require_non_empty_string(args.get("agent_name"), "agent_name")
    task = _require_non_empty_string(args.get("task"), "task")
    return {"ok": True, "output": json.dumps({"agent_name": agent_name, "task": task}, ensure_ascii=True)}


delegate_tool = Tool(
    type="agent",
    definition=FunctionToolDefinition(
        name="delegate",
        description="Delegate a task to another named agent.",
        parameters={
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": "The child agent name to delegate to.",
                },
                "task": {
                    "type": "string",
                    "description": "The task to give to the child agent.",
                },
            },
            "required": ["agent_name", "task"],
            "additionalProperties": False,
        },
    ),
    handler=handle_delegate,
)
