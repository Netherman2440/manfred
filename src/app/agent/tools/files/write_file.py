from __future__ import annotations

from typing import Any

from app.agent.tools.files.common import (
    WORKSPACE_ROOT,
    build_filesystem_tool,
    display_path,
    ensure_string_argument,
    ensure_text_argument,
    resolve_tool_path,
)


async def write_file_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
    del signal
    path = ensure_string_argument(args, "path")
    content = ensure_text_argument(args, "content")
    full_path = resolve_tool_path(path)

    if full_path.exists() and not full_path.is_file():
        raise IsADirectoryError(f"Cannot overwrite directory: {path}")

    full_path.write_text(content, encoding="utf-8")

    return {
        "ok": True,
        "output": {
            "path": display_path(full_path),
            "message": f"File written: {display_path(full_path)}",
        },
    }


write_file_tool = build_filesystem_tool(
    name="write_file",
    description=f"Write UTF-8 text to a file inside the workspace root ({WORKSPACE_ROOT}).",
    properties={
        "path": {
            "type": "string",
            "description": "Relative path to a file within the workspace.",
        },
        "content": {
            "type": "string",
            "description": "Full file content to write.",
        },
    },
    required=["path", "content"],
    handler=write_file_handler,
)
