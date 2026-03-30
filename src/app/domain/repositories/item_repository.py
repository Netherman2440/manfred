from __future__ import annotations

from sqlalchemy import select

from app.db.models import ItemModel
from app.domain.item import Item
from app.domain.repositories.base import SqlAlchemyRepository
from app.domain.types import ItemType, MessageRole


class ItemRepository(SqlAlchemyRepository):
    def get(self, item_id: str) -> Item | None:
        with self._session() as session:
            model = session.get(ItemModel, item_id)
            return None if model is None else self._to_domain(model)

    def list_by_session(self, session_id: str) -> list[Item]:
        with self._session() as session:
            models = session.scalars(
                select(ItemModel)
                .where(ItemModel.session_id == session_id)
                .order_by(ItemModel.sequence.asc(), ItemModel.created_at.asc())
            ).all()
            return [self._to_domain(model) for model in models]

    def list_by_agent(self, agent_id: str) -> list[Item]:
        with self._session() as session:
            models = session.scalars(
                select(ItemModel)
                .where(ItemModel.agent_id == agent_id)
                .order_by(ItemModel.sequence.asc(), ItemModel.created_at.asc())
            ).all()
            return [self._to_domain(model) for model in models]

    def save(self, item: Item) -> Item:
        with self._session() as session:
            model = session.get(ItemModel, item.id)
            if model is None:
                model = ItemModel(id=item.id)

            if item.role is None:
                raise ValueError("Item.role cannot be None")

            model.session_id = item.session_id
            model.agent_id = item.agent_id
            model.sequence = item.sequence
            model.type = item.type.value
            model.role = item.role.value
            model.content = item.content
            model.call_id = item.call_id
            model.name = item.name
            model.arguments_json = item.arguments_json
            model.output = item.output
            model.is_error = item.is_error
            model.created_at = item.created_at

            session.add(model)
            session.commit()
            session.refresh(model)
            return self._to_domain(model)

    @staticmethod
    def _to_domain(model: ItemModel) -> Item:
        return Item(
            id=model.id,
            session_id=model.session_id,
            agent_id=model.agent_id,
            sequence=model.sequence,
            type=ItemType(model.type),
            role=MessageRole(model.role),
            content=model.content,
            call_id=model.call_id,
            name=model.name,
            arguments_json=model.arguments_json,
            output=model.output,
            is_error=model.is_error,
            created_at=model.created_at,
        )
