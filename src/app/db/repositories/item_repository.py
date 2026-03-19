import uuid
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.item import ItemModel
from app.domain.item import Item
from app.domain.types import ItemType, MessageRole


class ItemRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def create(
        self,
        *,
        session_id: str,
        agent_id: str,
        sequence: int,
        item_type: ItemType,
        role: MessageRole | None = None,
        content: str | None = None,
        call_id: str | None = None,
        name: str | None = None,
        arguments_json: str | None = None,
        output: str | None = None,
        is_error: bool = False,
        item_id: str | None = None,
    ) -> Item:
        entity = ItemModel(
            id=item_id or str(uuid.uuid4()),
            session_id=session_id,
            agent_id=agent_id,
            sequence=sequence,
            type=item_type.value,
            role=role.value if role else None,
            content=content,
            call_id=call_id,
            name=name,
            arguments_json=arguments_json,
            output=output,
            is_error=is_error,
        )
        with self._session_factory() as session:
            session.add(entity)
            session.commit()
            session.refresh(entity)
            return self._to_domain(entity)

    def get_by_id(self, item_id: str) -> Item | None:
        with self._session_factory() as session:
            entity = session.get(ItemModel, item_id)
            return self._to_domain(entity) if entity else None

    def list_all(self) -> list[Item]:
        with self._session_factory() as session:
            entities = session.scalars(select(ItemModel).order_by(ItemModel.created_at)).all()
            return [self._to_domain(entity) for entity in entities]

    def list_by_agent(self, agent_id: str) -> list[Item]:
        with self._session_factory() as session:
            entities = session.scalars(
                select(ItemModel)
                .where(ItemModel.agent_id == agent_id)
                .order_by(ItemModel.sequence)
            ).all()
            return [self._to_domain(entity) for entity in entities]

    def get_last_sequence(self, agent_id: str) -> int:
        items = self.list_by_agent(agent_id)
        return items[-1].sequence if items else 0

    def update(self, item: Item) -> Item:
        with self._session_factory() as session:
            entity = session.get(ItemModel, item.id)
            if entity is None:
                raise ValueError(f"Item {item.id} does not exist.")

            entity.session_id = item.session_id
            entity.agent_id = item.agent_id
            entity.sequence = item.sequence
            entity.type = item.type.value
            entity.role = item.role.value if item.role else None
            entity.content = item.content
            entity.call_id = item.call_id
            entity.name = item.name
            entity.arguments_json = item.arguments_json
            entity.output = item.output
            entity.is_error = item.is_error
            session.commit()
            session.refresh(entity)
            return self._to_domain(entity)

    def delete(self, item_id: str) -> bool:
        with self._session_factory() as session:
            entity = session.get(ItemModel, item_id)
            if entity is None:
                return False
            session.delete(entity)
            session.commit()
            return True

    @staticmethod
    def _to_domain(entity: ItemModel) -> Item:
        return Item(
            id=entity.id,
            session_id=entity.session_id,
            agent_id=entity.agent_id,
            sequence=entity.sequence,
            type=ItemType(entity.type),
            role=MessageRole(entity.role) if entity.role else None,
            content=entity.content,
            call_id=entity.call_id,
            name=entity.name,
            arguments_json=entity.arguments_json,
            output=entity.output,
            is_error=entity.is_error,
            created_at=entity.created_at,
        )
