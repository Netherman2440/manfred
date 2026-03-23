from __future__ import annotations

from typing import Any

from app.agent.tools.files.common import (
    WORKSPACE_ROOT,
    build_filesystem_tool,
    display_path,
    expected_file_error,
    file_not_found_error,
    validate_string_argument,
    validate_workspace_path,
)
from app.domain.tool import tool_ok


async def delete_file_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
    del signal
    path = validate_string_argument(
        args,
        "path",
        tool_name="delete_file",
        hint="Podaj pole 'path' jako ścieżkę do istniejącego pliku w workspace.",
    )
    if isinstance(path, dict):
        return path

    full_path = validate_workspace_path(path, tool_name="delete_file")
    if isinstance(full_path, dict):
        return full_path

    if not full_path.exists():
        return file_not_found_error("delete_file", path)
    if not full_path.is_file():
        return expected_file_error("delete_file", path)

    full_path.unlink()

    return tool_ok(
        {
            "path": display_path(full_path),
            "message": f"File deleted: {display_path(full_path)}",
        }
    )


delete_file_tool = build_filesystem_tool(
    name="delete_file",
    description=f"Delete a file from the workspace root ({WORKSPACE_ROOT}).",
    properties={
        "path": {
            "type": "string",
            "description": "Relative path to the file within the workspace.",
        },
    },
    required=["path"],
    handler=delete_file_handler,
)
