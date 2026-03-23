from __future__ import annotations

from typing import Any

from app.agent.tools.files.common import (
    WORKSPACE_ROOT,
    build_filesystem_tool,
    display_path,
    path_not_found_error,
    to_isoformat,
    validate_string_argument,
    validate_workspace_path,
)
from app.domain.tool import tool_ok


async def file_info_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
    del signal
    path = validate_string_argument(
        args,
        "path",
        tool_name="file_info",
        hint="Podaj pole 'path' jako ścieżkę do pliku lub katalogu w workspace.",
    )
    if isinstance(path, dict):
        return path

    full_path = validate_workspace_path(path, tool_name="file_info")
    if isinstance(full_path, dict):
        return full_path

    if not full_path.exists():
        return path_not_found_error("file_info", path)

    stats = full_path.stat()
    created_timestamp = getattr(stats, "st_birthtime", stats.st_ctime)

    return tool_ok(
        {
            "path": display_path(full_path),
            "name": full_path.name or ".",
            "type": "directory" if full_path.is_dir() else "file",
            "size": stats.st_size,
            "created": to_isoformat(created_timestamp),
            "modified": to_isoformat(stats.st_mtime),
        }
    )


file_info_tool = build_filesystem_tool(
    name="file_info",
    description=f"Get metadata for a file or directory inside the workspace root ({WORKSPACE_ROOT}).",
    properties={
        "path": {
            "type": "string",
            "description": "Relative path to a file or directory within the workspace.",
        },
    },
    required=["path"],
    handler=file_info_handler,
)
