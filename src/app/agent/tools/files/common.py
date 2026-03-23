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


def ensure_string_argument(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(f"Tool expects a non-empty string argument: '{key}'.")
    return value


def ensure_text_argument(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Tool expects a string argument: '{key}'.")
    return value


def resolve_tool_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        raise ValueError("Path must be relative to the workspace root.")

    resolved_path = (WORKSPACE_ROOT / candidate).resolve(strict=False)
    try:
        resolved_path.relative_to(WORKSPACE_ROOT)
    except ValueError as exc:
        raise ValueError("Path escapes the workspace root.") from exc

    return resolved_path


def validate_string_argument(
    args: dict[str, Any],
    key: str,
    *,
    tool_name: str,
    allow_empty: bool = False,
    strip_value: bool = True,
    hint: str | None = None,
) -> str | ToolResult:
    value = args.get(key)
    if not isinstance(value, str):
        expected = "string" if allow_empty else "non-empty string"
        return tool_error(
            f"{tool_name} expects {expected} argument: '{key}'.",
            hint=hint or f"Podaj pole '{key}' jako {expected}.",
            details={
                "received": {key: value},
                "expected": {key: expected},
            },
        )

    normalized = value.strip() if strip_value else value
    if not allow_empty and normalized == "":
        return tool_error(
            f"{tool_name} expects a non-empty string argument: '{key}'.",
            hint=hint or f"Podaj pole '{key}' jako niepusty string.",
            details={
                "received": {key: value},
                "expected": {key: "non-empty string"},
            },
        )

    return normalized


def validate_workspace_path(path: str, *, tool_name: str) -> Path | ToolResult:
    candidate = Path(path)
    if candidate.is_absolute():
        return tool_error(
            f"{tool_name} expects a relative workspace path.",
            hint="Podaj ścieżkę względną względem workspace, np. 'notes/todo.txt'.",
            details={
                "path": path,
                "expected": "relative path inside workspace",
            },
        )

    resolved_path = (WORKSPACE_ROOT / candidate).resolve(strict=False)
    try:
        resolved_path.relative_to(WORKSPACE_ROOT)
    except ValueError:
        return tool_error(
            f"{tool_name} path escapes the workspace root.",
            hint="Użyj ścieżki wewnątrz workspace bez '..' wychodzących poza katalog roboczy.",
            details={
                "path": path,
                "workspace_root": str(WORKSPACE_ROOT),
            },
        )

    return resolved_path


def file_not_found_error(tool_name: str, path: str) -> ToolResult:
    return tool_error(
        f"{tool_name} could not find the requested file.",
        hint="Sprawdź ścieżkę albo użyj list_files dla katalogu nadrzędnego.",
        details={"path": path, "expected": "existing file"},
    )


def path_not_found_error(tool_name: str, path: str) -> ToolResult:
    return tool_error(
        f"{tool_name} could not find the requested path.",
        hint="Sprawdź ścieżkę albo użyj list_files dla katalogu nadrzędnego.",
        details={"path": path, "expected": "existing path"},
    )


def expected_file_error(tool_name: str, path: str) -> ToolResult:
    return tool_error(
        f"{tool_name} expected a file but received a directory.",
        hint="Podaj ścieżkę do pliku albo użyj list_files, jeśli chcesz obejrzeć zawartość katalogu.",
        details={"path": path, "expected": "file"},
    )


def expected_directory_error(tool_name: str, path: str) -> ToolResult:
    return tool_error(
        f"{tool_name} expected a directory.",
        hint="Podaj ścieżkę do katalogu. Jeśli chcesz odczytać plik, użyj read_file.",
        details={"path": path, "expected": "directory"},
    )


def cannot_overwrite_directory_error(tool_name: str, path: str) -> ToolResult:
    return tool_error(
        f"{tool_name} cannot overwrite a directory.",
        hint="Wskaż ścieżkę do pliku. Jeśli chcesz utworzyć katalog, użyj create_directory.",
        details={"path": path, "expected": "file path"},
    )


def display_path(path: Path) -> str:
    if path == WORKSPACE_ROOT:
        return "."
    return path.relative_to(WORKSPACE_ROOT).as_posix()


def to_isoformat(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


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
