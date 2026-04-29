from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from app.domain import Session, User


_NON_ALNUM_PATTERN = re.compile(r"[^a-z0-9._-]+")


@dataclass(slots=True, frozen=True)
class UserWorkspaceLayout:
    workspace_key: str
    root: Path
    sessions_root: Path
    agents_root: Path


@dataclass(slots=True, frozen=True)
class SessionWorkspaceLayout:
    user_workspace: UserWorkspaceLayout
    root: Path
    input_dir: Path
    output_dir: Path
    notes_file: Path


class WorkspaceLayoutService:
    def __init__(
        self,
        *,
        repo_root: Path,
        workspace_path: str,
        workspaces_dir_name: str = "workspaces",
        sessions_dir_name: str = "sessions",
        agents_dir_name: str = "agents",
        input_dir_name: str = "input",
        output_dir_name: str = "output",
        notes_file_name: str = "notes.md",
    ) -> None:
        workspace_root = Path(workspace_path)
        self.workspace_root = (
            (repo_root / workspace_root).resolve()
            if not workspace_root.is_absolute()
            else workspace_root.resolve()
        )
        self.workspaces_root = self.workspace_root / workspaces_dir_name
        self.sessions_dir_name = sessions_dir_name
        self.agents_dir_name = agents_dir_name
        self.input_dir_name = input_dir_name
        self.output_dir_name = output_dir_name
        self.notes_file_name = notes_file_name

    def resolve_user_workspace(
        self,
        *,
        user_id: str | None,
        user_name: str | None,
    ) -> UserWorkspaceLayout:
        workspace_key = self.resolve_user_workspace_key(user_id=user_id, user_name=user_name)
        root = self.workspaces_root / workspace_key
        return UserWorkspaceLayout(
            workspace_key=workspace_key,
            root=root,
            sessions_root=root / self.sessions_dir_name,
            agents_root=root / self.agents_dir_name,
        )

    def ensure_user_workspace(self, user: User) -> UserWorkspaceLayout:
        layout = self.resolve_user_workspace(user_id=user.id, user_name=user.name)
        layout.sessions_root.mkdir(parents=True, exist_ok=True)
        layout.agents_root.mkdir(parents=True, exist_ok=True)
        return layout

    def ensure_session_workspace(self, *, user: User, session: Session) -> SessionWorkspaceLayout:
        user_workspace = self.ensure_user_workspace(user)
        session_date_root = user_workspace.sessions_root / session.created_at.strftime("%Y/%m/%d")
        session_root = session_date_root / session.id
        input_dir = session_root / self.input_dir_name
        output_dir = session_root / self.output_dir_name
        notes_file = session_root / self.notes_file_name

        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        notes_file.touch(exist_ok=True)

        return SessionWorkspaceLayout(
            user_workspace=user_workspace,
            root=session_root,
            input_dir=input_dir,
            output_dir=output_dir,
            notes_file=notes_file,
        )

    def resolve_user_workspace_key(
        self,
        *,
        user_id: str | None,
        user_name: str | None,
    ) -> str:
        for raw_value in (user_name, user_id):
            normalized = self._normalize_segment(raw_value)
            if normalized:
                return normalized
        raise ValueError("Unable to resolve workspace directory for user.")

    @staticmethod
    def _normalize_segment(value: str | None) -> str:
        if value is None:
            return ""

        normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        normalized = normalized.strip().lower()
        normalized = _NON_ALNUM_PATTERN.sub("-", normalized)
        normalized = normalized.strip(".-_/")
        return normalized
