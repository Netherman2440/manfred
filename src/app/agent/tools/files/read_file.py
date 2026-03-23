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


async def read_file_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
    del signal
    path = validate_string_argument(
        args,
        "path",
        tool_name="read_file",
        hint="Podaj pole 'path' jako ścieżkę do istniejącego pliku tekstowego w workspace.",
    )
    if isinstance(path, dict):
        return path

    full_path = validate_workspace_path(path, tool_name="read_file")
    if isinstance(full_path, dict):
        return full_path

    if not full_path.exists():
        return file_not_found_error("read_file", path)
    if not full_path.is_file():
        return expected_file_error("read_file", path)

    return tool_ok(
        {
            "path": display_path(full_path),
            "content": full_path.read_text(encoding="utf-8"),
        }
    )


read_file_tool = build_filesystem_tool(
    name="read_file",
    description=f"Read a UTF-8 text file from the workspace root ({WORKSPACE_ROOT}).",
    properties={
        "path": {
            "type": "string",
            "description": "Relative path to a file within the workspace.",
        },
    },
    required=["path"],
    handler=read_file_handler,
)
