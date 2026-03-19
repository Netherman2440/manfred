from __future__ import annotations

from typing import Any

from app.agent.tools.files.common import WORKSPACE_ROOT, build_filesystem_tool, display_path, ensure_string_argument, resolve_tool_path


async def delete_file_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
    del signal
    path = ensure_string_argument(args, "path")
    full_path = resolve_tool_path(path)

    if not full_path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not full_path.is_file():
        raise IsADirectoryError(f"Not a file: {path}")

    full_path.unlink()

    return {
        "ok": True,
        "output": {
            "path": display_path(full_path),
            "message": f"File deleted: {display_path(full_path)}",
        },
    }


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
