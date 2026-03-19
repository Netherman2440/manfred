from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import BASE_DIR, Settings
from app.domain.tool import FunctionToolDefinition, Tool


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
