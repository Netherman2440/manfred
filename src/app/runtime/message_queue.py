from __future__ import annotations

from app.db.base import utcnow
from app.domain import Agent, Item, QueuedInput
from app.domain.repositories import ItemRepository, QueuedInputRepository
from collections.abc import Callable


class SessionMessageQueue:
    def __init__(
        self,
        *,
        queued_input_repository: QueuedInputRepository,
        item_repository: ItemRepository,
    ) -> None:
        self.queued_input_repository = queued_input_repository
        self.item_repository = item_repository

    def list_pending(self, session_id: str, agent_id: str) -> list[QueuedInput]:
        return self.queued_input_repository.get_pending_for_session_agent(session_id, agent_id)

    def pending_count(self, session_id: str, agent_id: str) -> int:
        return self.queued_input_repository.get_pending_count(session_id, agent_id)



    def consume_into_items(
        self,
        *,
        agent: Agent,
        item_factory: Callable[[QueuedInput], Item],
    ) -> list[Item]:
        pending = self.list_pending(agent.session_id, agent.id)
        if not pending:
            return []

        materialized: list[Item] = []
        for queued_input in pending:
            item = item_factory(queued_input)
            materialized.append(self.item_repository.save(item))
            self.queued_input_repository.consume(queued_input.id, utcnow())
        return materialized

    def clear_pending(self, session_id: str, agent_id: str) -> None:
        self.queued_input_repository.delete_pending_for_session_agent(session_id, agent_id)
