from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.domain import Session, User
from app.services.workspace_layout.models import SessionWorkspaceLayout, UserWorkspaceLayout


class BaseWorkspaceLayout(ABC):
    @property
    @abstractmethod
    def fs_root(self) -> Path: ...

    @abstractmethod
    def resolve_user_workspace_key(
        self,
        *,
        user_id: str | None,
        user_name: str | None,
    ) -> str: ...

    @abstractmethod
    def resolve_user_workspace(
        self,
        *,
        user_id: str | None,
        user_name: str | None,
    ) -> UserWorkspaceLayout: ...

    @abstractmethod
    def ensure_user_workspace(self, user: User) -> UserWorkspaceLayout: ...

    @abstractmethod
    def ensure_session_workspace(self, *, user: User, session: Session) -> SessionWorkspaceLayout: ...

    @abstractmethod
    def resolve_user_mount_root(
        self,
        *,
        user_id: str | None,
        user_name: str | None,
        mount_name: str,
    ) -> Path: ...

    @abstractmethod
    def resolve_agent_dir(
        self,
        *,
        user_id: str | None,
        user_name: str | None,
        agent_name: str,
    ) -> Path: ...

    @abstractmethod
    def resolve_agent_memory_path(
        self,
        *,
        user_id: str | None,
        user_name: str | None,
        agent_name: str,
    ) -> Path: ...
