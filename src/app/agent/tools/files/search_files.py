from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.agent.tools.files.common import WORKSPACE_ROOT, build_filesystem_tool, display_path, ensure_string_argument


async def search_files_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
    del signal
    query = ensure_string_argument(args, "query")
    query_bytes = query.encode("utf-8")
    matches: list[str] = []

    for current_root, dirnames, filenames in os.walk(WORKSPACE_ROOT, followlinks=False):
        dirnames.sort()
        filenames.sort()
        root_path = Path(current_root)

        for filename in filenames:
            full_path = root_path / filename

            try:
                if query_bytes in full_path.read_bytes():
                    matches.append(display_path(full_path))
            except OSError:
                continue

    return {
        "ok": True,
        "output": {
            "query": query,
            "matches": matches,
        },
    }


search_files_tool = build_filesystem_tool(
    name="search_files",
    description=f"Search all files in the workspace root ({WORKSPACE_ROOT}) and return files containing the exact query string.",
    properties={
        "query": {
            "type": "string",
            "description": "Exact UTF-8 text to search for in workspace files.",
        },
    },
    required=["query"],
    handler=search_files_handler,
)
