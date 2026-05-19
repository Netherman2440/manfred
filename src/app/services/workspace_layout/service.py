from __future__ import annotations

import logging
import re
import shutil
import unicodedata
from pathlib import Path

from app.domain import Session, User
from app.services.workspace_layout.base import BaseWorkspaceLayout
from app.services.workspace_layout.models import SessionWorkspaceLayout, UserWorkspaceLayout

logger = logging.getLogger(__name__)


_NON_ALNUM_PATTERN = re.compile(r"[^a-z0-9._-]+")

AGENTS_MOUNT_NAME = "agents"
AGENT_MEMORY_FILE = "memory.md"


class WorkspaceLayoutService(BaseWorkspaceLayout):
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
        self._fs_root = (repo_root / fs_root).resolve() if not fs_root.is_absolute() else fs_root.resolve()
        self.agent_mount_names = agent_mount_names or []
        self.default_agent_source_dir = default_agent_source_dir

        normalized_default_agent_name = default_agent_name.strip()
        if (
            not normalized_default_agent_name
            or normalized_default_agent_name in {".", ".."}
            or Path(normalized_default_agent_name).name != normalized_default_agent_name
            or any(sep in normalized_default_agent_name for sep in ("/", "\\"))
        ):
            raise ValueError("default_agent_name must be a single safe path segment.")
        self.default_agent_name = normalized_default_agent_name

        self.files_dir_name = files_dir_name
        self.attachments_dir_name = attachments_dir_name
        self.plan_file_name = plan_file_name

    @property
    def fs_root(self) -> Path:
        return self._fs_root

    def resolve_user_workspace(
        self,
        *,
        user_id: str | None,
        user_name: str | None,
    ) -> UserWorkspaceLayout:
        workspace_key = self.resolve_user_workspace_key(user_id=user_id, user_name=user_name)
        root = self._fs_root / workspace_key
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

        if self.default_agent_source_dir and not self.default_agent_source_dir.is_dir():
            logger.warning(
                "Configured default_agent_source_dir is missing or not a directory; seeding skipped: %s",
                self.default_agent_source_dir,
            )
        elif self.default_agent_source_dir:
            agents_root = layout.root / AGENTS_MOUNT_NAME
            main_target = agents_root / self.default_agent_name
            self._copytree_if_absent(self.default_agent_source_dir, main_target)

            siblings_root = self.default_agent_source_dir.parent
            if siblings_root.is_dir():
                for sibling in sorted(siblings_root.iterdir()):
                    if not sibling.is_dir() or sibling == self.default_agent_source_dir:
                        continue
                    self._copytree_if_absent(sibling, agents_root / sibling.name)

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

    def resolve_user_mount_root(
        self,
        *,
        user_id: str | None,
        user_name: str | None,
        mount_name: str,
    ) -> Path:
        layout = self.resolve_user_workspace(user_id=user_id, user_name=user_name)
        return layout.root / mount_name

    def resolve_agent_dir(
        self,
        *,
        user_id: str | None,
        user_name: str | None,
        agent_name: str,
    ) -> Path:
        agents_root = self.resolve_user_mount_root(
            user_id=user_id,
            user_name=user_name,
            mount_name=AGENTS_MOUNT_NAME,
        )
        return agents_root / agent_name

    def resolve_agent_memory_path(
        self,
        *,
        user_id: str | None,
        user_name: str | None,
        agent_name: str,
    ) -> Path:
        return (
            self.resolve_agent_dir(
                user_id=user_id,
                user_name=user_name,
                agent_name=agent_name,
            )
            / AGENT_MEMORY_FILE
        )

    @staticmethod
    def _copytree_if_absent(source: Path, target: Path) -> None:
        if target.exists():
            return
        try:
            shutil.copytree(source, target)
        except FileExistsError:
            pass
        except OSError:
            logger.error(
                "Failed to copy default agent %s → %s",
                source,
                target,
                exc_info=True,
            )

    @staticmethod
    def _normalize_segment(value: str | None) -> str:
        if value is None:
            return ""

        normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        normalized = normalized.strip().lower()
        normalized = _NON_ALNUM_PATTERN.sub("-", normalized)
        normalized = normalized.strip(".-_/")
        return normalized
