from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import UserModel
from app.domain.user import User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, user_id: str) -> User | None:
        model = self.session.get(UserModel, user_id)
        return None if model is None else self._to_domain(model)

    def list(self) -> list[User]:
        models = self.session.scalars(select(UserModel).order_by(UserModel.created_at.asc())).all()
        return [self._to_domain(model) for model in models]

    def save(self, user: User) -> User:
        model = self.session.get(UserModel, user.id)
        if model is None:
            model = UserModel(id=user.id)

        model.name = user.name
        model.api_key_hash = user.api_key_hash
        model.created_at = user.created_at

        self.session.add(model)
        return self._to_domain(model)

    @staticmethod
    def _to_domain(model: UserModel) -> User:
        return User(
            id=model.id,
            name=model.name,
            api_key_hash=model.api_key_hash,
            created_at=model.created_at,
        )
