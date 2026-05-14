from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import Settings
from app.domain.tool import FunctionToolDefinition, Tool, ToolExecutionContext
from app.tools.definitions.aidevs.common import REQUEST_TIMEOUT, hub_base, require_api_key


def build_submit_task_tool(settings: Settings) -> Tool:
    async def handle_submit_task(args: dict[str, Any], context: ToolExecutionContext) -> dict[str, bool | str]:
        del context
        task = args.get("task")
        if not isinstance(task, str) or not task.strip():
            raise ValueError("'task' must be a non-empty string")
        if "answer" not in args:
            raise ValueError("'answer' is required")

        api_key = require_api_key(settings)
        payload = {"apikey": api_key, "task": task.strip(), "answer": args["answer"]}
        url = f"{hub_base(settings)}/verify"

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            try:
                response = await client.post(url, json=payload)
            except httpx.HTTPError as exc:
                return {"ok": False, "error": f"HTTP error contacting {url}: {exc}"}

        body_text = response.text
        try:
            body_parsed: Any = response.json()
        except ValueError:
            body_parsed = body_text

        output = {
            "status": response.status_code,
            "body": body_parsed if body_parsed != body_text else body_text,
        }
        return {"ok": True, "output": json.dumps(output, ensure_ascii=False)}

    return Tool(
        type="sync",
        definition=FunctionToolDefinition(
            name="submit_task",
            description=(
                "Submit an AI devs task solution to hub.ag3nts.org/verify. "
                "The 'apikey' is injected from config (AI_DEVS_API_KEY) — do NOT pass it. "
                "Returns the hub response verbatim, including {FLG:...} on success or an error string."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Task name, e.g. 'people', 'drone', 'findhim', 'proxy', 'sendit', 'railway'.",
                    },
                    "answer": {
                        "description": (
                            "Answer payload — shape depends on the task: array of strings (drone), "
                            "array of objects (people), object (findhim), plain string (sendit). "
                            "Pass the bare answer; do not wrap it with apikey/task."
                        ),
                    },
                },
                "required": ["task", "answer"],
                "additionalProperties": False,
            },
        ),
        handler=handle_submit_task,
    )
