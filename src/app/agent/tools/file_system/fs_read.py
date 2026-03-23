from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
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
    validate_int_argument,
    validate_string_argument,
    validate_string_list_argument,
)
from app.agent.tools.file_system.line_ops import add_line_numbers, parse_line_range, text_to_lines
from app.agent.tools.file_system.path_guard import path_kind, resolve_workspace_path
from app.agent.tools.file_system.text_utils import is_text_file, read_utf8_text
from app.domain.tool import tool_ok


FS_READ_PROPERTIES = {
    "path": {
        "type": "string",
        "description": "Relative path to a file or directory inside the workspace.",
    },
    "lines": {
        "type": "string",
        "description": "Optional 1-based line range for file reads, for example '10-20'.",
    },
    "depth": {
        "type": "integer",
        "description": "Directory listing depth. 1 means direct children only.",
        "default": 1,
    },
    "limit": {
        "type": "integer",
        "description": "Maximum number of directory entries to return.",
        "default": 200,
    },
    "offset": {
        "type": "integer",
        "description": "Directory listing offset after filtering.",
        "default": 0,
    },
    "glob": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Optional glob filters matched against relative paths.",
    },
    "exclude": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Optional glob excludes matched against relative paths.",
    },
    "types": {
        "type": "array",
        "items": {"type": "string", "enum": ["file", "directory"]},
        "description": "Optional entry types to include for directory listings.",
    },
    "details": {
        "type": "boolean",
        "description": "Include size and modified time for directory entries.",
        "default": False,
    },
}


def _matches_filters(relative_path: str, entry_type: str, *, include: list[str], exclude: list[str], types: set[str]) -> bool:
    if types and entry_type not in types:
        return False
    if include and not any(fnmatch(relative_path, pattern) for pattern in include):
        return False
    if exclude and any(fnmatch(relative_path, pattern) for pattern in exclude):
        return False
    return True


def _iter_entries(root: Path, *, max_depth: int) -> list[tuple[Path, str]]:
    collected: list[tuple[Path, str]] = []

    def visit(current: Path, depth: int) -> None:
        if depth >= max_depth:
            return

        children = sorted(current.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower(), item.name))
        for child in children:
            child_type = "directory" if child.is_dir() else "file"
            collected.append((child, child_type))
            if child.is_dir():
                visit(child, depth + 1)

    visit(root, 0)
    return collected


async def fs_read_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
    del signal
    path = validate_string_argument(args, "path", tool_name="fs_read", default=".")
    if isinstance(path, dict):
        return path

    lines = args.get("lines")
    if lines is not None and not isinstance(lines, str):
        return invalid_argument_error("fs_read", "lines", expected="string line range", received=lines)

    depth = validate_int_argument(args, "depth", tool_name="fs_read", default=1, min_value=0)
    if isinstance(depth, dict):
        return depth
    limit = validate_int_argument(args, "limit", tool_name="fs_read", default=200, min_value=1)
    if isinstance(limit, dict):
        return limit
    offset = validate_int_argument(args, "offset", tool_name="fs_read", default=0, min_value=0)
    if isinstance(offset, dict):
        return offset
    include = validate_string_list_argument(args, "glob", tool_name="fs_read")
    if isinstance(include, dict):
        return include
    exclude = validate_string_list_argument(args, "exclude", tool_name="fs_read")
    if isinstance(exclude, dict):
        return exclude
    raw_types = validate_string_list_argument(args, "types", tool_name="fs_read")
    if isinstance(raw_types, dict):
        return raw_types
    details = validate_bool_argument(args, "details", tool_name="fs_read", default=False)
    if isinstance(details, dict):
        return details

    invalid_types = [entry_type for entry_type in raw_types if entry_type not in {"file", "directory"}]
    if invalid_types:
        return invalid_argument_error(
            "fs_read",
            "types",
            expected="list containing only 'file' or 'directory'",
            received=raw_types,
        )

    resolved = resolve_workspace_path(path, tool_name="fs_read")
    if isinstance(resolved, dict):
        return resolved

    kind = path_kind(resolved)
    if kind == "missing":
        return operation_error(
            "fs_read",
            "fs_read could not find the requested path.",
            hint="Sprawdź ścieżkę albo wylistuj katalog nadrzędny przez fs_read na katalogu.",
            details={"path": path, "expected": "existing file or directory"},
        )

    if kind == "file":
        if not is_text_file(resolved):
            return operation_error(
                "fs_read",
                "fs_read supports only UTF-8 text files.",
                hint="Użyj fs_manage/stat dla metadanych albo wskaż plik tekstowy.",
                details={"path": display_path(resolved), "expected": "utf-8 text file"},
            )

        raw_content = read_utf8_text(resolved)
        all_lines = text_to_lines(raw_content)
        start = 1
        end = len(all_lines)

        if lines is not None:
            try:
                start, end = parse_line_range(lines, total_lines=len(all_lines))
            except ValueError as exc:
                return invalid_argument_error("fs_read", "lines", expected=str(exc), received=lines)
            selected_lines = all_lines[start - 1 : end]
        else:
            selected_lines = all_lines

        numbered = add_line_numbers(selected_lines, start=start)
        return tool_ok(
            {
                "success": True,
                "path": display_path(resolved),
                "type": "file",
                "checksum": short_checksum(raw_content),
                "line_start": start,
                "line_end": end,
                "total_lines": len(all_lines),
                "content": numbered,
            }
        )

    requested_root = resolved
    entries = []
    for child, entry_type in _iter_entries(requested_root, max_depth=depth):
        relative_path = child.relative_to(requested_root).as_posix()
        if not _matches_filters(relative_path, entry_type, include=include, exclude=exclude, types=set(raw_types)):
            continue

        payload = {"path": display_path(child), "name": child.name, "type": entry_type}
        if details:
            payload.update({key: value for key, value in serialize_stat(child).items() if key not in {"path", "name", "type"}})
        entries.append(payload)

    visible_entries = entries[offset : offset + limit]
    return tool_ok(
        {
            "success": True,
            "path": display_path(requested_root),
            "type": "directory",
            "entries": visible_entries,
            "count": len(visible_entries),
            "total": len(entries),
            "workspace_root": str(WORKSPACE_ROOT),
        }
    )


fs_read_tool = build_filesystem_tool(
    name="fs_read",
    description=f"Read a UTF-8 text file with line numbers or list a directory inside the workspace root ({WORKSPACE_ROOT}).",
    properties=FS_READ_PROPERTIES,
    required=["path"],
    handler=fs_read_handler,
)
