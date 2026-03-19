from __future__ import annotations

from typing import Any

from app.agent.tools.files.common import WORKSPACE_ROOT, build_filesystem_tool, display_path, ensure_string_argument, resolve_tool_path


async def list_files_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
    del signal
    path = ensure_string_argument(args, "path")
    full_path = resolve_tool_path(path)

    if not full_path.exists():
        raise FileNotFoundError(f"Path not found: {path}")
    if not full_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {path}")

    entries = [
        {
            "name": entry.name,
            "type": "directory" if entry.is_dir() else "file",
        }
        for entry in sorted(full_path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower(), item.name))
    ]

    return {
        "ok": True,
        "output": {
            "path": display_path(full_path),
            "entries": entries,
        },
    }


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
