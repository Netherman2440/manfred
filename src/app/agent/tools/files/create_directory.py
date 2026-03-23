from __future__ import annotations

from typing import Any

from app.agent.tools.files.common import WORKSPACE_ROOT, build_filesystem_tool, display_path, validate_string_argument, validate_workspace_path
from app.domain.tool import tool_ok


async def create_directory_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
    del signal
    path = validate_string_argument(
        args,
        "path",
        tool_name="create_directory",
        hint="Podaj pole 'path' jako niepusty string ze ścieżką względną w workspace.",
    )
    if isinstance(path, dict):
        return path

    full_path = validate_workspace_path(path, tool_name="create_directory")
    if isinstance(full_path, dict):
        return full_path

    full_path.mkdir(parents=True, exist_ok=True)

    return tool_ok(
        {
            "path": display_path(full_path),
            "message": f"Directory created: {display_path(full_path)}",
        }
    )


create_directory_tool = build_filesystem_tool(
    name="create_directory",
    description=f"Create a directory inside the workspace root ({WORKSPACE_ROOT}).",
    properties={
        "path": {
            "type": "string",
            "description": "Relative path to the directory within the workspace.",
        },
    },
    required=["path"],
    handler=create_directory_handler,
)
