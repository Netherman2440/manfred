from __future__ import annotations

from typing import Any

from app.domain.tool import FunctionToolDefinition, Tool, tool_error, tool_ok


DELEGATE_DEFINITION = FunctionToolDefinition(
    name="delegate",
    description="Delegate a task to another backend-defined agent template.",
    parameters={
        "type": "object",
        "properties": {
            "agent": {
                "type": "string",
                "description": "Agent template name from workspace/agents, for example 'azazel'.",
            },
            "task": {
                "type": "string",
                "description": "Task to be executed by the delegated agent.",
            },
        },
        "required": ["agent", "task"],
        "additionalProperties": False,
    },
)


async def delegate_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
    del signal

    agent_name = args.get("agent")
    task = args.get("task")
    if not isinstance(agent_name, str) or agent_name.strip() == "":
        return tool_error(
            "delegate expects a non-empty string argument: 'agent'.",
            hint="Podaj nazwę template'u agenta, np. 'azazel'.",
            details={"received": {"agent": agent_name}},
        )
    if not isinstance(task, str) or task.strip() == "":
        return tool_error(
            "delegate expects a non-empty string argument: 'task'.",
            hint="Podaj opis zadania, które ma wykonać subagent.",
            details={"received": {"task": task}},
        )

    return tool_ok(
        {
            "agent": agent_name.strip(),
            "task": task.strip(),
        }
    )


delegate_tool = Tool(
    type="agent",
    definition=DELEGATE_DEFINITION,
    handler=delegate_handler,
)
