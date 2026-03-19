from __future__ import annotations

from typing import Any

from app.agent.tools.files.common import WORKSPACE_ROOT, build_filesystem_tool, display_path, ensure_string_argument, resolve_tool_path


async def create_directory_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
    del signal
    path = ensure_string_argument(args, "path")
    full_path = resolve_tool_path(path)
    full_path.mkdir(parents=True, exist_ok=True)

    return {
        "ok": True,
        "output": {
            "path": display_path(full_path),
            "message": f"Directory created: {display_path(full_path)}",
        },
    }


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
