from __future__ import annotations

from typing import Any

from app.agent.tools.files.common import (
    WORKSPACE_ROOT,
    build_filesystem_tool,
    display_path,
    expected_directory_error,
    path_not_found_error,
    validate_string_argument,
    validate_workspace_path,
)
from app.domain.tool import tool_ok


async def list_files_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
    del signal
    path = validate_string_argument(
        args,
        "path",
        tool_name="list_files",
        hint="Podaj pole 'path' jako ścieżkę do katalogu w workspace. Użyj '.' dla katalogu głównego.",
    )
    if isinstance(path, dict):
        return path

    full_path = validate_workspace_path(path, tool_name="list_files")
    if isinstance(full_path, dict):
        return full_path

    if not full_path.exists():
        return path_not_found_error("list_files", path)
    if not full_path.is_dir():
        return expected_directory_error("list_files", path)

    entries = [
        {
            "name": entry.name,
            "type": "directory" if entry.is_dir() else "file",
        }
        for entry in sorted(full_path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower(), item.name))
    ]

    return tool_ok(
        {
            "path": display_path(full_path),
            "entries": entries,
        }
    )


list_files_tool = build_filesystem_tool(
    name="list_files",
    description=f"List files and directories within the workspace root ({WORKSPACE_ROOT}).",
    properties={
        "path": {
            "type": "string",
            "description": "Relative path within the workspace. Use '.' for the workspace root.",
        },
    },
    required=["path"],
    handler=list_files_handler,
)
