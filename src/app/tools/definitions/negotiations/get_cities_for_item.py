from __future__ import annotations

import json
from typing import Any

from app.domain.tool import FunctionToolDefinition, Tool, ToolExecutionContext
from app.services.aidevs.negotiations import BaseNegotiationsService


def build_get_cities_for_item_tool(negotiations_service: BaseNegotiationsService) -> Tool:
    async def handle(
        args: dict[str, Any],
        context: ToolExecutionContext,
    ) -> dict[str, Any]:
        del context

        raw_name = args.get("item_name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            return {"ok": False, "error": "'item_name' must be a non-empty string"}

        try:
            cities = negotiations_service.get_cities_for_item(raw_name)
        except FileNotFoundError as exc:
            return {"ok": False, "error": str(exc)}

        names = [c.name for c in cities]
        payload = {
            "item_name": raw_name,
            "returned": len(names),
            "names": names,
        }
        return {"ok": True, "output": json.dumps(payload, ensure_ascii=False)}

    description = (
        "Return the list of city names that sell the given item. "
        "REQUIRES the EXACT item name from the catalog (case-insensitive). "
        "If the user's request is natural language, first call `list_items` to resolve "
        "the exact name, then call this. Returns `names` — a list of city names. "
        "Empty `names` means no city sells this item (or the name does not match the catalog)."
    )

    return Tool(
        type="sync",
        definition=FunctionToolDefinition(
            name="get_cities_for_item",
            description=description,
            parameters={
                "type": "object",
                "properties": {
                    "item_name": {
                        "type": "string",
                        "description": "Exact item name from the catalog.",
                    },
                },
                "required": ["item_name"],
                "additionalProperties": False,
            },
        ),
        handler=handle,
    )
