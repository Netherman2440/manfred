from __future__ import annotations

from sqlalchemy import select

from app.db.models import UserModel
from app.domain.repositories.base import SqlAlchemyRepository
from app.domain.user import User


class UserRepository(SqlAlchemyRepository):
    def get(self, user_id: str) -> User | None:
        with self._session() as session:
            model = session.get(UserModel, user_id)
            return None if model is None else self._to_domain(model)

    def list(self) -> list[User]:
        with self._session() as session:
            models = session.scalars(select(UserModel).order_by(UserModel.created_at.asc())).all()
            return [self._to_domain(model) for model in models]

    def save(self, user: User) -> User:
        with self._session() as session:
            model = session.get(UserModel, user.id)
            if model is None:
                model = UserModel(id=user.id)

            model.name = user.name
            model.api_key_hash = user.api_key_hash
            model.created_at = user.created_at

            session.add(model)
            session.commit()
            session.refresh(model)
            return self._to_domain(model)

    @staticmethod
    def _to_domain(model: UserModel) -> User:
        return User(
            id=model.id,
            name=model.name,
            api_key_hash=model.api_key_hash,
            created_at=model.created_at,
        )
