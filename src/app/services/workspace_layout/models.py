from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class UserWorkspaceLayout:
    workspace_key: str
    root: Path  # fs_root / user_key
    workspaces_root: Path  # fs_root / user_key / workspaces


@dataclass(slots=True, frozen=True)
class SessionWorkspaceLayout:
    user_workspace: UserWorkspaceLayout
    root: Path  # workspaces_root / date / session_id
    files_dir: Path  # root / files
    attachments_dir: Path  # root / attachments
    plan_file: Path  # root / plan.md
