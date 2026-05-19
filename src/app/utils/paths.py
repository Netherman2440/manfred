from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.filesystem import WorkspaceLayoutService


def get_repo_root() -> Path:
    """Return the absolute path to the backend repo root (`manfred_backend/`)."""
    return Path(__file__).resolve().parents[3]


def resolve_relative_path(path: str | Path, *, base: Path) -> Path:
    """Resolve `path` against `base` if it's not already absolute."""
    p = Path(path)
    return (base / p).resolve() if not p.is_absolute() else p.resolve()


def default_user_workspace_path(
    *,
    workspace_layout_service: WorkspaceLayoutService,
    default_user_id: str,
    default_user_name: str | None,
) -> str:
    """Return the absolute filesystem path string of the default user's workspace root."""
    layout = workspace_layout_service.resolve_user_workspace(
        user_id=default_user_id,
        user_name=default_user_name,
    )
    return str(layout.root)
