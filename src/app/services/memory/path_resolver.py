from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from app.domain.repositories import UserRepository
from app.services.filesystem import WorkspaceLayoutService


class MemoryPathResolver:
    def __init__(
        self,
        *,
        workspace_layout_service: WorkspaceLayoutService,
        session_factory: Callable[[], Session],
    ) -> None:
        self._workspace_layout_service = workspace_layout_service
        self._session_factory = session_factory

    def __call__(self, user_id: str, agent_name: str) -> Path:
        sa_session = self._session_factory()
        try:
            user = UserRepository(sa_session).get(user_id)
            user_name = user.name if user is not None else None
        finally:
            sa_session.close()
        layout = self._workspace_layout_service.resolve_user_workspace(
            user_id=user_id,
            user_name=user_name,
        )
        return layout.root / "agents" / agent_name / "memory.md"
