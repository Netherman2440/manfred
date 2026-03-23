from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import BASE_DIR, Settings
from app.domain.tool import FunctionToolDefinition, Tool, ToolResult, tool_error


def _resolve_workspace_root(raw_path: str) -> Path:
    configured_path = Path(raw_path).expanduser()
    if not configured_path.is_absolute():
        configured_path = BASE_DIR / configured_path
    return configured_path.resolve(strict=False)


SETTINGS = Settings()
WORKSPACE_ROOT = _resolve_workspace_root(SETTINGS.WORKSPACE_ROOT)
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)


def display_path(path: Path) -> str:
    if path == WORKSPACE_ROOT:
        return "."
    return path.relative_to(WORKSPACE_ROOT).as_posix()


def build_filesystem_tool(
    *,
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
    handler: Any,
) -> Tool:
    return Tool(
        type="sync",
        definition=FunctionToolDefinition(
            name=name,
            description=description,
            parameters={
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        ),
        handler=handler,
    )


def invalid_argument_error(
    tool_name: str,
    key: str,
    *,
    expected: str,
    received: Any,
    hint: str | None = None,
) -> ToolResult:
    return tool_error(
        f"{tool_name} received an invalid argument: '{key}'.",
        hint=hint or f"Podaj pole '{key}' jako {expected}.",
        details={
            "argument": key,
            "expected": expected,
            "received": received,
        },
    )


def path_error(tool_name: str, path: str, *, message: str, hint: str, code: str, expected: str | None = None) -> ToolResult:
    details: dict[str, Any] = {
        "path": path,
        "code": code,
        "workspace_root": str(WORKSPACE_ROOT),
    }
    if expected is not None:
        details["expected"] = expected

    return tool_error(
        message,
        hint=hint,
        details=details,
    )


def operation_error(tool_name: str, message: str, *, hint: str, details: dict[str, Any] | None = None) -> ToolResult:
    return tool_error(message, hint=hint, details=details)


def validate_string_argument(
    args: dict[str, Any],
    key: str,
    *,
    tool_name: str,
    allow_empty: bool = False,
    default: str | None = None,
    strip_value: bool = True,
) -> str | ToolResult:
    value = args.get(key, default)
    if not isinstance(value, str):
        expected = "string" if allow_empty else "non-empty string"
        return invalid_argument_error(tool_name, key, expected=expected, received=value)

    normalized = value.strip() if strip_value else value
    if not allow_empty and normalized == "":
        return invalid_argument_error(tool_name, key, expected="non-empty string", received=value)

    return normalized


def validate_bool_argument(args: dict[str, Any], key: str, *, tool_name: str, default: bool = False) -> bool | ToolResult:
    value = args.get(key, default)
    if not isinstance(value, bool):
        return invalid_argument_error(tool_name, key, expected="boolean", received=value)
    return value


def validate_int_argument(
    args: dict[str, Any],
    key: str,
    *,
    tool_name: str,
    default: int,
    min_value: int | None = None,
) -> int | ToolResult:
    value = args.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        return invalid_argument_error(tool_name, key, expected="integer", received=value)
    if min_value is not None and value < min_value:
        return invalid_argument_error(
            tool_name,
            key,
            expected=f"integer >= {min_value}",
            received=value,
        )
    return value


def validate_string_list_argument(
    args: dict[str, Any],
    key: str,
    *,
    tool_name: str,
    default: list[str] | None = None,
) -> list[str] | ToolResult:
    value = args.get(key, default if default is not None else [])
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or item.strip() == "" for item in value):
        return invalid_argument_error(tool_name, key, expected="list of non-empty strings", received=value)
    return [item.strip() for item in value]


def to_isoformat(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def serialize_stat(path: Path) -> dict[str, Any]:
    stat_result = path.stat()
    return {
        "path": display_path(path),
        "name": path.name or ".",
        "type": "directory" if path.is_dir() else "file",
        "size": stat_result.st_size,
        "modified_at": to_isoformat(stat_result.st_mtime),
    }
