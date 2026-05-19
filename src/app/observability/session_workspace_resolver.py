from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from app.domain.repositories import SessionRepository


class SessionWorkspaceResolver:
    def __init__(self, *, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def __call__(self, session_id: str) -> Path | None:
        sa_session = self._session_factory()
        try:
            session = SessionRepository(sa_session).get(session_id)
            if session is None or not session.workspace_path:
                return None
            return Path(session.workspace_path)
        finally:
            sa_session.close()
