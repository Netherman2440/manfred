from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import SessionModel
from app.domain.session import Session
from app.domain.types import SessionStatus


class SessionRepository:
    def __init__(self, session: DbSession) -> None:
        self.session = session

    def get(self, session_id: str) -> Session | None:
        model = self.session.get(SessionModel, session_id)
        return None if model is None else self._to_domain(model)

    def list_by_user(self, user_id: str) -> list[Session]:
        models = self.session.scalars(
            select(SessionModel)
            .where(SessionModel.user_id == user_id)
            .order_by(SessionModel.updated_at.desc())
        ).all()
        return [self._to_domain(model) for model in models]

    def save(self, domain_session: Session) -> Session:
        model = self.session.get(SessionModel, domain_session.id)
        if model is None:
            model = SessionModel(id=domain_session.id)

        model.user_id = domain_session.user_id
        model.root_agent_id = domain_session.root_agent_id
        model.status = domain_session.status.value
        model.title = domain_session.title
        model.created_at = domain_session.created_at
        model.updated_at = domain_session.updated_at

        self.session.add(model)
        return self._to_domain(model)

    @staticmethod
    def _to_domain(model: SessionModel) -> Session:
        return Session(
            id=model.id,
            user_id=model.user_id,
            root_agent_id=model.root_agent_id,
            status=SessionStatus(model.status),
            title=model.title,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
