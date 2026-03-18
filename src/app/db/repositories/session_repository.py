import uuid
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.session import SessionModel
from app.domain.session import Session as SessionDomain
from app.domain.types import SessionStatus


class SessionRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def create(
        self,
        user_id: str,
        *,
        session_id: str | None = None,
        root_agent_id: str | None = None,
        status: SessionStatus = SessionStatus.ACTIVE,
        summary: str | None = None,
    ) -> SessionDomain:
        entity = SessionModel(
            id=session_id or str(uuid.uuid4()),
            user_id=user_id,
            root_agent_id=root_agent_id,
            status=status.value,
            summary=summary,
        )
        with self._session_factory() as session:
            session.add(entity)
            session.commit()
            session.refresh(entity)
            return self._to_domain(entity)

    def get_by_id(self, session_id: str) -> SessionDomain | None:
        with self._session_factory() as session:
            entity = session.get(SessionModel, session_id)
            return self._to_domain(entity) if entity else None

    def list_all(self) -> list[SessionDomain]:
        with self._session_factory() as session:
            entities = session.scalars(
                select(SessionModel).order_by(SessionModel.created_at)
            ).all()
            return [self._to_domain(entity) for entity in entities]

    def list_by_user(self, user_id: str) -> list[SessionDomain]:
        with self._session_factory() as session:
            entities = session.scalars(
                select(SessionModel)
                .where(SessionModel.user_id == user_id)
                .order_by(SessionModel.created_at)
            ).all()
            return [self._to_domain(entity) for entity in entities]

    def update(self, session_domain: SessionDomain) -> SessionDomain:
        with self._session_factory() as session:
            entity = session.get(SessionModel, session_domain.id)
            if entity is None:
                raise ValueError(f"Session {session_domain.id} does not exist.")

            entity.user_id = session_domain.user_id
            entity.root_agent_id = session_domain.root_agent_id
            entity.status = session_domain.status.value
            entity.summary = session_domain.summary
            session.commit()
            session.refresh(entity)
            return self._to_domain(entity)

    def delete(self, session_id: str) -> bool:
        with self._session_factory() as session:
            entity = session.get(SessionModel, session_id)
            if entity is None:
                return False
            session.delete(entity)
            session.commit()
            return True

    @staticmethod
    def _to_domain(entity: SessionModel) -> SessionDomain:
        return SessionDomain(
            id=entity.id,
            user_id=entity.user_id,
            root_agent_id=entity.root_agent_id,
            status=SessionStatus(entity.status),
            summary=entity.summary,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )
