from __future__ import annotations

from typing import Any

from app.agent.tools.files.common import (
    WORKSPACE_ROOT,
    build_filesystem_tool,
    cannot_overwrite_directory_error,
    display_path,
    validate_string_argument,
    validate_workspace_path,
)
from app.domain.tool import tool_ok


async def write_file_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
    del signal
    path = validate_string_argument(
        args,
        "path",
        tool_name="write_file",
        hint="Podaj pole 'path' jako ścieżkę do pliku w workspace.",
    )
    if isinstance(path, dict):
        return path

    content = validate_string_argument(
        args,
        "content",
        tool_name="write_file",
        allow_empty=True,
        strip_value=False,
        hint="Podaj pole 'content' jako string z pełną treścią pliku.",
    )
    if isinstance(content, dict):
        return content

    full_path = validate_workspace_path(path, tool_name="write_file")
    if isinstance(full_path, dict):
        return full_path

    if full_path.exists() and not full_path.is_file():
        return cannot_overwrite_directory_error("write_file", path)

    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content, encoding="utf-8")

    return tool_ok(
        {
            "path": display_path(full_path),
            "message": f"File written: {display_path(full_path)}",
        }
    )


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
