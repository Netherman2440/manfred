from __future__ import annotations

from typing import Any

from app.domain.tool import Tool, ToolExecutionContext, WebSearchToolDefinition


async def handle_web_search(args: dict[str, Any], context: ToolExecutionContext) -> dict[str, bool | str]:
    del args, context
    return {
        "ok": False,
        "error": "web_search is executed server-side by OpenRouter and must not be dispatched locally",
    }


web_search_tool = Tool(
    type="sync",
    definition=WebSearchToolDefinition(),
    handler=handle_web_search,
)
