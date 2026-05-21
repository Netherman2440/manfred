from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import Settings
from app.domain.tool import FunctionToolDefinition, Tool, ToolExecutionContext
from app.tools.definitions.aidevs.common import REQUEST_TIMEOUT, hub_base, require_api_key

ZMAIL_PATH = "/api/zmail"


def build_mail_api_tool(settings: Settings) -> Tool:
    async def handle_mail_api(args: dict[str, Any], context: ToolExecutionContext) -> dict[str, bool | str]:
        del context
        body = args.get("body")
        if not isinstance(body, dict):
            raise ValueError("'body' must be a JSON object")
        if "action" not in body or not isinstance(body["action"], str) or not body["action"].strip():
            raise ValueError("'body.action' is required (start with action='help' to discover the API)")
        if "apikey" in body:
            raise ValueError("Do not pass 'apikey' in body — it is injected by the tool")

        api_key = require_api_key(settings)
        payload = {**body, "apikey": api_key}
        url = f"{hub_base(settings)}{ZMAIL_PATH}"

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
            name="mail_api",
            description=(
                "POST to hub.ag3nts.org/api/zmail. The 'apikey' is injected from config "
                "(AI_DEVS_API_KEY) — do NOT include it in 'body'. You construct the full request "
                "payload yourself; start with body={'action': 'help', 'page': 1} to discover "
                "supported actions and their parameters. Returns the hub response verbatim "
                "(status + parsed JSON body)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "body": {
                        "type": "object",
                        "description": (
                            "Full request body for /api/zmail except 'apikey'. Must include 'action' "
                            "(e.g. 'help', 'getInbox', and any other actions revealed by 'help'). "
                            "Add whatever other fields the action requires (e.g. 'page', 'query', 'id')."
                        ),
                        "properties": {
                            "action": {
                                "type": "string",
                                "description": "Required. Start with 'help' to discover the API.",
                            },
                        },
                        "required": ["action"],
                        "additionalProperties": True,
                    },
                },
                "required": ["body"],
                "additionalProperties": False,
            },
        ),
        handler=handle_mail_api,
    )
