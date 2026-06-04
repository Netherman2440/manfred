from __future__ import annotations

import json
from typing import Any

from app.domain.tool import FunctionToolDefinition, Tool, ToolExecutionContext
from app.services.aidevs.negotiations import BaseNegotiationsService

DEFAULT_LIMIT = 10
MAX_LIMIT = 50


def build_list_items_tool(negotiations_service: BaseNegotiationsService) -> Tool:
    async def handle(
        args: dict[str, Any],
        context: ToolExecutionContext,
    ) -> dict[str, Any]:
        del context

        raw_query = args.get("query")
        if not isinstance(raw_query, str) or not raw_query.strip():
            return {"ok": False, "error": "'query' must be a non-empty string"}

        raw_limit = args.get("limit", DEFAULT_LIMIT)
        if isinstance(raw_limit, bool) or not isinstance(raw_limit, int):
            return {"ok": False, "error": "'limit' must be an integer"}
        limit = max(1, min(MAX_LIMIT, raw_limit))

        try:
            matches = negotiations_service.search_items(raw_query, limit=limit)
        except (ValueError, FileNotFoundError) as exc:
            return {"ok": False, "error": str(exc)}

        names = [i.name for i in matches]
        payload = {
            "query": raw_query,
            "returned": len(names),
            "names": names,
        }
        return {"ok": True, "output": json.dumps(payload, ensure_ascii=False)}

    description = (
        "Search the item catalog by substring. Returns up to `limit` exact item names "
        "(case-insensitive substring match). Use this to resolve a user's natural-language "
        "description (e.g. 'kabel 10 metrów', 'rezystor 1k') to the EXACT name expected by "
        "`get_cities_for_item`. Returns only `names` — pick one and pass it back verbatim. "
        "If the query is broad (e.g. 'kabel'), narrow it with more terms before calling again."
    )

    return Tool(
        type="sync",
        definition=FunctionToolDefinition(
            name="list_items",
            description=description,
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Substring to match against item names (case-insensitive).",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_LIMIT,
                        "description": f"Max names returned. Default {DEFAULT_LIMIT}, max {MAX_LIMIT}.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        handler=handle,
    )
