from __future__ import annotations

from pathlib import Path

from app.agent.tools.file_system.common import WORKSPACE_ROOT, path_error
from app.domain.tool import ToolResult


def resolve_workspace_path(path: str, *, tool_name: str) -> Path | ToolResult:
    candidate = Path(path)
    if candidate.is_absolute():
        return path_error(
            tool_name,
            path,
            message=f"{tool_name} expects a relative workspace path.",
            hint="Podaj ścieżkę względną względem workspace, np. 'notes/todo.txt'.",
            code="absolute_path_not_allowed",
            expected="relative path inside workspace",
        )

    resolved = (WORKSPACE_ROOT / candidate).resolve(strict=False)
    try:
        resolved.relative_to(WORKSPACE_ROOT)
    except ValueError:
        return path_error(
            tool_name,
            path,
            message=f"{tool_name} path escapes the workspace root.",
            hint="Użyj ścieżki wewnątrz workspace bez '..' i bez symlinków wychodzących poza katalog roboczy.",
            code="path_escape",
            expected="path inside workspace",
        )

    return resolved


def path_kind(path: Path) -> str:
    if path.is_dir():
        return "directory"
    if path.is_file():
        return "file"
    return "missing"
