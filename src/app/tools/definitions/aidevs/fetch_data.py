from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings
from app.domain.tool import FunctionToolDefinition, Tool, ToolExecutionContext
from app.tools.definitions.aidevs.common import (
    FILENAME_PATTERN,
    REQUEST_TIMEOUT,
    SESSION_FILES_DIRNAME,
    hub_base,
    require_api_key,
)


def build_fetch_aidevs_data_tool(settings: Settings) -> Tool:
    async def handle_fetch_aidevs_data(args: dict[str, Any], context: ToolExecutionContext) -> dict[str, bool | str]:
        raw_filename = args.get("filename")
        if not isinstance(raw_filename, str):
            raise ValueError("'filename' must be a string")
        filename = raw_filename.strip()
        if not filename:
            raise ValueError("'filename' must not be empty")
        if not FILENAME_PATTERN.match(filename):
            raise ValueError(
                "'filename' must be a single path segment (letters, digits, dot, underscore, hyphen — no slashes)"
            )

        if not context.workspace_path:
            raise ValueError("fetch_aidevs_data requires an active session workspace — no workspace_path on context")

        api_key = require_api_key(settings)
        url = f"{hub_base(settings)}/data/{api_key}/{filename}"

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            try:
                response = await client.get(url)
            except httpx.HTTPError as exc:
                return {"ok": False, "error": f"HTTP error fetching {filename}: {exc}"}

        content_type = response.headers.get("content-type", "").lower()
        files_dir = Path(context.workspace_path) / SESSION_FILES_DIRNAME
        files_dir.mkdir(parents=True, exist_ok=True)
        target_path = files_dir / filename
        target_path.write_bytes(response.content)

        output = {
            "status": response.status_code,
            "content_type": content_type,
            "bytes": len(response.content),
            "path": f"workspace/{SESSION_FILES_DIRNAME}/{filename}",
            "hint": "Use read_file with the returned path to inspect contents.",
        }
        return {"ok": True, "output": json.dumps(output, ensure_ascii=False)}

    return Tool(
        type="sync",
        definition=FunctionToolDefinition(
            name="fetch_aidevs_data",
            description=(
                "Download an AI devs course data file from hub.ag3nts.org and persist it to the "
                "current session workspace at workspace/files/<filename>. Returns only metadata "
                "(status, content_type, bytes, workspace-relative path) — the body is NOT inlined "
                "to keep the context small. Use read_file on the returned path to read the contents "
                "or a slice of them. Provide only the filename (e.g. 'failure.log'); the tool builds "
                "hub.ag3nts.org/data/<apikey>/<filename> server-side and injects AI_DEVS_API_KEY."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": (
                            "Filename on the hub, e.g. 'failure.log', 'people.json', 'cenzura.txt'. "
                            "Single path segment only — no slashes, no leading directories. Used both "
                            "as the URL suffix and the on-disk name in workspace/files/."
                        ),
                    },
                },
                "required": ["filename"],
                "additionalProperties": False,
            },
        ),
        handler=handle_fetch_aidevs_data,
    )
