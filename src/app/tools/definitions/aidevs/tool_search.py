from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import Settings
from app.domain.tool import FunctionToolDefinition, Tool, ToolExecutionContext
from app.tools.definitions.aidevs.common import REQUEST_TIMEOUT, hub_base, require_api_key

TOOLSEARCH_PATH = "/api/toolsearch"


def build_tool_search_tool(settings: Settings) -> Tool:
    async def handle_tool_search(args: dict[str, Any], context: ToolExecutionContext) -> dict[str, bool | str]:
        del context
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("'query' must be a non-empty string")

        api_key = require_api_key(settings)
        payload = {"apikey": api_key, "query": query.strip()}
        url = f"{hub_base(settings)}{TOOLSEARCH_PATH}"

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
            name="tool_search",
            description=(
                "Search the AI devs task toolbox at hub.ag3nts.org/api/toolsearch. "
                "The 'apikey' is injected from config (AI_DEVS_API_KEY) — do NOT pass it. "
                "Accepts natural language or keywords in 'query' (English only per task brief). "
                "Returns up to 3 best-matching tool descriptors as JSON; the hub does not return all entries. "
                "Use this to discover task-specific tools and their endpoints/parameters."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Search query in English — natural language or keywords describing what you need "
                            "(e.g. 'movement rules and terrain', 'vehicle fuel consumption', 'map of region')."
                        ),
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        handler=handle_tool_search,
    )
