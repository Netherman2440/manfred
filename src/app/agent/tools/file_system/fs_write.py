from __future__ import annotations

from typing import Any

from app.agent.tools.file_system.checksum import short_checksum
from app.agent.tools.file_system.common import (
    WORKSPACE_ROOT,
    build_filesystem_tool,
    display_path,
    invalid_argument_error,
    operation_error,
    validate_bool_argument,
    validate_string_argument,
)
from app.agent.tools.file_system.diff_utils import build_unified_diff
from app.agent.tools.file_system.line_ops import (
    delete_lines,
    insert_after_line,
    insert_before_line,
    lines_to_text,
    normalize_text,
    parse_line_range,
    replace_lines,
    text_to_lines,
)
from app.agent.tools.file_system.path_guard import path_kind, resolve_workspace_path
from app.agent.tools.file_system.text_utils import is_text_file, read_utf8_text
from app.domain.tool import tool_ok


FS_WRITE_PROPERTIES = {
    "path": {
        "type": "string",
        "description": "Relative file path inside the workspace.",
    },
    "operation": {
        "type": "string",
        "enum": ["create", "update"],
    },
    "content": {
        "type": "string",
        "description": "Full content for create, or inserted / replacement content for updates.",
    },
    "create_dirs": {
        "type": "boolean",
        "default": False,
    },
    "action": {
        "type": "string",
        "enum": ["replace", "insert_before", "insert_after", "delete_lines"],
    },
    "lines": {
        "type": "string",
        "description": "1-based line range for update actions, for example '4-6'.",
    },
    "checksum": {
        "type": "string",
        "description": "Checksum from fs_read used to protect against stale writes.",
    },
    "dry_run": {
        "type": "boolean",
        "default": False,
    },
}


def _require_content(args: dict[str, Any], *, tool_name: str) -> str | dict[str, Any]:
    content = validate_string_argument(args, "content", tool_name=tool_name, allow_empty=True, strip_value=False)
    if isinstance(content, dict):
        return content
    return content


async def fs_write_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
    del signal
    path = validate_string_argument(args, "path", tool_name="fs_write")
    if isinstance(path, dict):
        return path
    operation = validate_string_argument(args, "operation", tool_name="fs_write")
    if isinstance(operation, dict):
        return operation
    create_dirs = validate_bool_argument(args, "create_dirs", tool_name="fs_write", default=False)
    if isinstance(create_dirs, dict):
        return create_dirs
    dry_run = validate_bool_argument(args, "dry_run", tool_name="fs_write", default=False)
    if isinstance(dry_run, dict):
        return dry_run

    if operation not in {"create", "update"}:
        return invalid_argument_error("fs_write", "operation", expected="'create' or 'update'", received=operation)

    resolved = resolve_workspace_path(path, tool_name="fs_write")
    if isinstance(resolved, dict):
        return resolved

    if operation == "create":
        content = _require_content(args, tool_name="fs_write")
        if isinstance(content, dict):
            return content

        kind = path_kind(resolved)
        if kind == "directory":
            return operation_error(
                "fs_write",
                "fs_write cannot create a file over a directory.",
                hint="Wskaż ścieżkę do pliku, nie katalogu.",
                details={"path": path, "expected": "file path"},
            )
        if not create_dirs and not resolved.parent.exists():
            return operation_error(
                "fs_write",
                "fs_write parent directory does not exist.",
                hint="Ustaw 'create_dirs=true' albo utwórz katalog przez fs_manage.",
                details={"path": path, "parent": display_path(resolved.parent)},
            )

        normalized = normalize_text(content)
        diff = build_unified_diff(before="", after=normalized, path=display_path(resolved))
        if not dry_run:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(normalized, encoding="utf-8")

        return tool_ok(
            {
                "success": True,
                "path": display_path(resolved),
                "operation": operation,
                "applied": not dry_run,
                "checksum": short_checksum(normalized),
                "diff": diff,
            }
        )

    action = validate_string_argument(args, "action", tool_name="fs_write")
    if isinstance(action, dict):
        return action
    lines = validate_string_argument(args, "lines", tool_name="fs_write")
    if isinstance(lines, dict):
        return lines
    checksum = args.get("checksum")
    if checksum is not None and not isinstance(checksum, str):
        return invalid_argument_error("fs_write", "checksum", expected="string", received=checksum)

    if action not in {"replace", "insert_before", "insert_after", "delete_lines"}:
        return invalid_argument_error(
            "fs_write",
            "action",
            expected="'replace', 'insert_before', 'insert_after' or 'delete_lines'",
            received=action,
        )

    if path_kind(resolved) != "file":
        return operation_error(
            "fs_write",
            "fs_write update expects an existing file.",
            hint="Najpierw utwórz plik przez 'operation=create' albo sprawdź ścieżkę.",
            details={"path": path, "expected": "existing file"},
        )
    if not is_text_file(resolved):
        return operation_error(
            "fs_write",
            "fs_write update supports only UTF-8 text files.",
            hint="Wskaż plik tekstowy.",
            details={"path": display_path(resolved), "expected": "utf-8 text file"},
        )

    before = read_utf8_text(resolved)
    current_checksum = short_checksum(before)
    if checksum is not None and checksum != current_checksum:
        return operation_error(
            "fs_write",
            "fs_write checksum mismatch.",
            hint="Najpierw wykonaj fs_read i ponów zapis z aktualnym checksumem.",
            details={
                "path": display_path(resolved),
                "expected_checksum": current_checksum,
                "received_checksum": checksum,
                "code": "checksum_mismatch",
            },
        )

    existing_lines = text_to_lines(before)
    needs_content = action in {"replace", "insert_before", "insert_after"}
    content = ""
    if needs_content:
        content = _require_content(args, tool_name="fs_write")
        if isinstance(content, dict):
            return content
        new_lines = text_to_lines(content)
    else:
        new_lines = []

    try:
        start, end = parse_line_range(lines, total_lines=len(existing_lines), allow_empty_insert=action in {"insert_before", "insert_after"})
    except ValueError as exc:
        return invalid_argument_error("fs_write", "lines", expected=str(exc), received=lines)

    if action == "replace":
        updated_lines = replace_lines(existing_lines, start, end, new_lines)
    elif action == "insert_before":
        updated_lines = insert_before_line(existing_lines, start, new_lines)
    elif action == "insert_after":
        updated_lines = insert_after_line(existing_lines, end, new_lines)
    else:
        updated_lines = delete_lines(existing_lines, start, end)

    after = lines_to_text(updated_lines)
    diff = build_unified_diff(before=before, after=after, path=display_path(resolved))
    if not dry_run:
        resolved.write_text(after, encoding="utf-8")

    return tool_ok(
        {
            "success": True,
            "path": display_path(resolved),
            "operation": operation,
            "action": action,
            "applied": not dry_run,
            "checksum_before": current_checksum,
            "checksum_after": short_checksum(after),
            "diff": diff,
        }
    )


fs_write_tool = build_filesystem_tool(
    name="fs_write",
    description=f"Create text files or apply line-based edits with checksum protection inside the workspace root ({WORKSPACE_ROOT}).",
    properties=FS_WRITE_PROPERTIES,
    required=["path", "operation"],
    handler=fs_write_handler,
)
