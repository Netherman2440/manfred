import uuid
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.user import UserModel
from app.domain.user import User


class UserRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def create(
        self,
        name: str,
        *,
        api_key_hash: str | None = None,
        user_id: str | None = None,
    ) -> User:
        entity = UserModel(
            id=user_id or str(uuid.uuid4()),
            name=name,
            api_key_hash=api_key_hash,
        )
        with self._session_factory() as session:
            session.add(entity)
            session.commit()
            session.refresh(entity)
            return self._to_domain(entity)

    def get_by_id(self, user_id: str) -> User | None:
        with self._session_factory() as session:
            entity = session.get(UserModel, user_id)
            return self._to_domain(entity) if entity else None

    def list_all(self) -> list[User]:
        with self._session_factory() as session:
            entities = session.scalars(select(UserModel).order_by(UserModel.created_at)).all()
            return [self._to_domain(entity) for entity in entities]

    def update(self, user: User) -> User:
        with self._session_factory() as session:
            entity = session.get(UserModel, user.id)
            if entity is None:
                raise ValueError(f"User {user.id} does not exist.")

            entity.name = user.name
            entity.api_key_hash = user.api_key_hash
            session.commit()
            session.refresh(entity)
            return self._to_domain(entity)

    def delete(self, user_id: str) -> bool:
        with self._session_factory() as session:
            entity = session.get(UserModel, user_id)
            if entity is None:
                return False
            session.delete(entity)
            session.commit()
            return True

    @staticmethod
    def _to_domain(entity: UserModel) -> User:
        return User(
            id=entity.id,
            name=entity.name,
            api_key_hash=entity.api_key_hash,
            created_at=entity.created_at,
        )
