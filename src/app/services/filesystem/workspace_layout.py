from __future__ import annotations

import logging
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from app.domain import Session, User

logger = logging.getLogger(__name__)


_NON_ALNUM_PATTERN = re.compile(r"[^a-z0-9._-]+")


@dataclass(slots=True, frozen=True)
class UserWorkspaceLayout:
    workspace_key: str
    root: Path            # fs_root / user_key
    workspaces_root: Path # fs_root / user_key / workspaces


@dataclass(slots=True, frozen=True)
class SessionWorkspaceLayout:
    user_workspace: UserWorkspaceLayout
    root: Path            # workspaces_root / date / session_id
    files_dir: Path       # root / files
    attachments_dir: Path # root / attachments
    plan_file: Path       # root / plan.md


class WorkspaceLayoutService:
    def __init__(
        self,
        *,
        repo_root: Path,
        workspace_path: str,
        agent_mount_names: list[str] | None = None,
        default_agent_source_dir: Path | None = None,
        default_agent_name: str = "manfred",
        files_dir_name: str = "files",
        attachments_dir_name: str = "attachments",
        plan_file_name: str = "plan.md",
    ) -> None:
        fs_root = Path(workspace_path)
        self.fs_root = (
            (repo_root / fs_root).resolve()
            if not fs_root.is_absolute()
            else fs_root.resolve()
        )
        self.agent_mount_names = agent_mount_names or []
        self.default_agent_source_dir = default_agent_source_dir
        self.default_agent_name = default_agent_name
        self.files_dir_name = files_dir_name
        self.attachments_dir_name = attachments_dir_name
        self.plan_file_name = plan_file_name

    def resolve_user_workspace(
        self,
        *,
        user_id: str | None,
        user_name: str | None,
    ) -> UserWorkspaceLayout:
        workspace_key = self.resolve_user_workspace_key(user_id=user_id, user_name=user_name)
        root = self.fs_root / workspace_key
        return UserWorkspaceLayout(
            workspace_key=workspace_key,
            root=root,
            workspaces_root=root / "workspaces",
        )

    def ensure_user_workspace(self, user: User) -> UserWorkspaceLayout:
        layout = self.resolve_user_workspace(user_id=user.id, user_name=user.name)
        for name in self.agent_mount_names:
            (layout.root / name).mkdir(parents=True, exist_ok=True)
        layout.workspaces_root.mkdir(parents=True, exist_ok=True)

        if self.default_agent_source_dir and self.default_agent_source_dir.is_dir():
            target = layout.root / "agents" / self.default_agent_name
            if not target.exists():
                try:
                    shutil.copytree(self.default_agent_source_dir, target)
                except FileExistsError:
                    pass
                except OSError:
                    logger.error(
                        "Failed to copy default agent %s → %s",
                        self.default_agent_source_dir,
                        target,
                        exc_info=True,
                    )

        return layout

    def ensure_session_workspace(self, *, user: User, session: Session) -> SessionWorkspaceLayout:
        user_workspace = self.ensure_user_workspace(user)
        session_date_root = user_workspace.workspaces_root / session.created_at.strftime("%Y/%m/%d")
        session_root = session_date_root / session.id
        files_dir = session_root / self.files_dir_name
        attachments_dir = session_root / self.attachments_dir_name
        plan_file = session_root / self.plan_file_name

        files_dir.mkdir(parents=True, exist_ok=True)
        attachments_dir.mkdir(parents=True, exist_ok=True)
        plan_file.touch(exist_ok=True)

        return SessionWorkspaceLayout(
            user_workspace=user_workspace,
            root=session_root,
            files_dir=files_dir,
            attachments_dir=attachments_dir,
            plan_file=plan_file,
        )

    def resolve_user_workspace_key(
        self,
        *,
        user_id: str | None,
        user_name: str | None,
    ) -> str:
        normalized_name = self._normalize_segment(user_name)
        normalized_user_id = self._normalize_segment(user_id)

        if normalized_name and normalized_user_id and normalized_name != normalized_user_id:
            return f"{normalized_name}-{normalized_user_id}"
        if normalized_name:
            return normalized_name
        if normalized_user_id:
            return normalized_user_id
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
