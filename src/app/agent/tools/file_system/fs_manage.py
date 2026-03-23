from __future__ import annotations

import shutil
from typing import Any

from app.agent.tools.file_system.checksum import short_checksum
from app.agent.tools.file_system.common import (
    WORKSPACE_ROOT,
    build_filesystem_tool,
    display_path,
    invalid_argument_error,
    operation_error,
    serialize_stat,
    validate_bool_argument,
    validate_string_argument,
)
from app.agent.tools.file_system.path_guard import path_kind, resolve_workspace_path
from app.agent.tools.file_system.text_utils import is_text_file, read_utf8_text
from app.domain.tool import tool_ok


FS_MANAGE_PROPERTIES = {
    "action": {
        "type": "string",
        "enum": ["mkdir", "stat", "rename", "move", "copy", "delete"],
    },
    "path": {
        "type": "string",
        "description": "Relative source path inside the workspace.",
    },
    "destination": {
        "type": "string",
        "description": "Relative destination path for rename, move and copy.",
    },
    "recursive": {
        "type": "boolean",
        "default": False,
    },
    "force": {
        "type": "boolean",
        "default": False,
    },
}


def _stat_payload(path: Any) -> dict[str, Any]:
    payload = serialize_stat(path)
    if path.is_file() and is_text_file(path):
        payload["checksum"] = short_checksum(read_utf8_text(path))
    return payload


async def fs_manage_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
    del signal
    action = validate_string_argument(args, "action", tool_name="fs_manage")
    if isinstance(action, dict):
        return action
    path = validate_string_argument(args, "path", tool_name="fs_manage")
    if isinstance(path, dict):
        return path
    recursive = validate_bool_argument(args, "recursive", tool_name="fs_manage", default=False)
    if isinstance(recursive, dict):
        return recursive
    force = validate_bool_argument(args, "force", tool_name="fs_manage", default=False)
    if isinstance(force, dict):
        return force

    if action not in {"mkdir", "stat", "rename", "move", "copy", "delete"}:
        return invalid_argument_error(
            "fs_manage",
            "action",
            expected="'mkdir', 'stat', 'rename', 'move', 'copy' or 'delete'",
            received=action,
        )

    resolved = resolve_workspace_path(path, tool_name="fs_manage")
    if isinstance(resolved, dict):
        return resolved

    if action == "mkdir":
        if path_kind(resolved) == "file":
            return operation_error(
                "fs_manage",
                "fs_manage mkdir cannot replace a file.",
                hint="Wskaż nowy katalog albo usuń istniejący plik.",
                details={"path": path},
            )
        resolved.mkdir(parents=True, exist_ok=True)
        return tool_ok(
            {
                "success": True,
                "action": action,
                "path": display_path(resolved),
                "type": "directory",
            }
        )

    if path_kind(resolved) == "missing":
        return operation_error(
            "fs_manage",
            "fs_manage could not find the requested path.",
            hint="Sprawdź ścieżkę źródłową.",
            details={"path": path, "expected": "existing path"},
        )

    if action == "stat":
        return tool_ok(
            {
                "success": True,
                "action": action,
                **_stat_payload(resolved),
            }
        )

    if action == "delete":
        if resolved.is_dir():
            if any(resolved.iterdir()):
                return operation_error(
                    "fs_manage",
                    "fs_manage delete only supports empty directories.",
                    hint="Najpierw usuń zawartość katalogu albo użyj innej ścieżki.",
                    details={"path": display_path(resolved), "code": "directory_not_empty"},
                )
            resolved.rmdir()
        else:
            resolved.unlink()
        return tool_ok(
            {
                "success": True,
                "action": action,
                "path": display_path(resolved),
            }
        )

    destination = validate_string_argument(args, "destination", tool_name="fs_manage")
    if isinstance(destination, dict):
        return destination
    target = resolve_workspace_path(destination, tool_name="fs_manage")
    if isinstance(target, dict):
        return target

    if action == "rename" and resolved.parent != target.parent:
        return operation_error(
            "fs_manage",
            "fs_manage rename keeps the item in the same directory.",
            hint="Użyj action='move' do przenoszenia między katalogami.",
            details={"path": display_path(resolved), "destination": destination},
        )

    if target.exists():
        if not force:
            return operation_error(
                "fs_manage",
                "fs_manage destination already exists.",
                hint="Użyj 'force=true' albo wskaż inną ścieżkę docelową.",
                details={"destination": display_path(target)},
            )
        if target.is_dir() and any(target.iterdir()):
            return operation_error(
                "fs_manage",
                "fs_manage cannot overwrite a non-empty directory.",
                hint="Wskaż pusty katalog docelowy albo inną ścieżkę.",
                details={"destination": display_path(target)},
            )
        if target.is_dir():
            target.rmdir()
        else:
            target.unlink()

    target.parent.mkdir(parents=True, exist_ok=True)

    if action in {"rename", "move"}:
        resolved.rename(target)
    elif action == "copy":
        if resolved.is_dir():
            if not recursive:
                return operation_error(
                    "fs_manage",
                    "fs_manage copy for directories requires recursive=true.",
                    hint="Ustaw 'recursive=true' dla kopiowania katalogu.",
                    details={"path": display_path(resolved)},
                )
            shutil.copytree(resolved, target)
        else:
            shutil.copy2(resolved, target)

    return tool_ok(
        {
            "success": True,
            "action": action,
            "path": display_path(resolved),
            "destination": display_path(target),
            "workspace_root": str(WORKSPACE_ROOT),
        }
    )


fs_manage_tool = build_filesystem_tool(
    name="fs_manage",
    description=f"Manage files and directories inside the workspace root ({WORKSPACE_ROOT}).",
    properties=FS_MANAGE_PROPERTIES,
    required=["action", "path"],
    handler=fs_manage_handler,
)
