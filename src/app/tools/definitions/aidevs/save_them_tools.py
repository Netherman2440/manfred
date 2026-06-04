from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import Settings
from app.domain.tool import FunctionToolDefinition, Tool, ToolExecutionContext
from app.tools.definitions.aidevs.common import REQUEST_TIMEOUT, hub_base, require_api_key

TOOL_URL_PATTERN = re.compile(r"^/api/[A-Za-z0-9_\-/]+$")


def build_save_them_tools_tool(settings: Settings) -> Tool:
    async def handle_save_them_tools(args: dict[str, Any], context: ToolExecutionContext) -> dict[str, bool | str]:
        del context
        tool_url = args.get("tool_url")
        if not isinstance(tool_url, str):
            raise ValueError("'tool_url' must be a string")
        tool_url = tool_url.strip()
        if not tool_url:
            raise ValueError("'tool_url' must be non-empty")
        if ".." in tool_url or "//" in tool_url.lstrip("/"):
            raise ValueError("'tool_url' must not contain '..' or '//'")
        if not TOOL_URL_PATTERN.match(tool_url):
            raise ValueError(
                "'tool_url' must be a path on hub.ag3nts.org starting with '/api/' "
                "(e.g. '/api/toolsearch', '/api/maps'). Pass only the path, not the full URL."
            )

        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("'query' must be a non-empty string")

        api_key = require_api_key(settings)
        payload = {"apikey": api_key, "query": query.strip()}
        url = f"{hub_base(settings)}{tool_url}"

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
            "tool_url": tool_url,
            "body": body_parsed,
        }
        return {"ok": True, "output": json.dumps(output, ensure_ascii=False)}

    return Tool(
        type="sync",
        definition=FunctionToolDefinition(
            name="save_them_tools",
            description=(
                "Call any tool on the AI devs hub for task 'savethem'. "
                "POSTs {apikey, query} to hub.ag3nts.org<tool_url>. "
                "The 'apikey' is injected from config (AI_DEVS_API_KEY) — do NOT pass it. "
                "Start with tool_url='/api/toolsearch' to discover other tools; the response "
                "contains a 'tools' array where each item has a 'url' field (e.g. '/api/maps', "
                "'/api/books'). Copy that 'url' verbatim into 'tool_url' on the next call. "
                "All tools accept the same 'query' parameter (English, natural language or keywords) "
                "and return up to 3 best matches. Tool returns the hub response verbatim."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "tool_url": {
                        "type": "string",
                        "description": (
                            "Path on hub.ag3nts.org starting with '/api/' "
                            "(e.g. '/api/toolsearch', '/api/maps', '/api/books'). "
                            "For the first call use '/api/toolsearch'; for follow-ups copy the "
                            "'url' field from a previous toolsearch response."
                        ),
                    },
                    "query": {
                        "type": "string",
                        "description": (
                            "Search query in English — natural language or keywords describing what "
                            "you need (e.g. 'movement rules and terrain', 'fuel consumption per vehicle')."
                        ),
                    },
                },
                "required": ["tool_url", "query"],
                "additionalProperties": False,
            },
        ),
        handler=handle_save_them_tools,
    )
