from __future__ import annotations

import json
from typing import Any

from app.domain.tool import FunctionToolDefinition, Tool, ToolExecutionContext
from app.services.aidevs.negotiations import BaseNegotiationsService

PAGE_SIZE = 10


def build_get_items_for_city_tool(negotiations_service: BaseNegotiationsService) -> Tool:
    async def handle(
        args: dict[str, Any],
        context: ToolExecutionContext,
    ) -> dict[str, Any]:
        del context

        raw_name = args.get("city_name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            return {"ok": False, "error": "'city_name' must be a non-empty string"}

        raw_page = args.get("page", 1)
        if isinstance(raw_page, bool) or not isinstance(raw_page, int):
            return {"ok": False, "error": "'page' must be a 1-based integer"}
        if raw_page < 1:
            return {"ok": False, "error": "'page' must be >= 1"}

        offset = (raw_page - 1) * PAGE_SIZE

        try:
            page = negotiations_service.get_items_for_city(
                raw_name,
                offset=offset,
                limit=PAGE_SIZE,
            )
        except (ValueError, FileNotFoundError) as exc:
            return {"ok": False, "error": str(exc)}

        total_pages = (page.total + PAGE_SIZE - 1) // PAGE_SIZE if page.total > 0 else 0
        names = [i.name for i in page.items]
        payload = {
            "city_name": raw_name,
            "page": raw_page,
            "total_pages": total_pages,
            "total_items": page.total,
            "page_size": PAGE_SIZE,
            "names": names,
            "has_more": (offset + len(names)) < page.total,
        }
        return {"ok": True, "output": json.dumps(payload, ensure_ascii=False)}

    description = (
        "Return one page of item names sold in the given city. "
        "REQUIRES the EXACT city name from the catalog (case-insensitive). "
        "If the user's request is natural language, first call `list_cities` to resolve "
        "the exact name, then call this. "
        f"Paginated — {PAGE_SIZE} items per page. `page` is 1-based. "
        "Response includes `total_pages` and `has_more` so you can iterate. "
        "Empty `names` with `total_items=0` means no items for this city (or unknown name)."
    )

    return Tool(
        type="sync",
        definition=FunctionToolDefinition(
            name="get_items_for_city",
            description=description,
            parameters={
                "type": "object",
                "properties": {
                    "city_name": {
                        "type": "string",
                        "description": "Exact city name from the catalog.",
                    },
                    "page": {
                        "type": "integer",
                        "minimum": 1,
                        "description": f"1-based page number. {PAGE_SIZE} items per page. Default 1.",
                    },
                },
                "required": ["city_name"],
                "additionalProperties": False,
            },
        ),
        handler=handle,
    )
