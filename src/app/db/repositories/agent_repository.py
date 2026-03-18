import uuid
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.agent import AgentModel
from app.domain.agent import Agent, AgentConfig
from app.domain.types import AgentStatus


class AgentRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def create(
        self,
        session_id: str,
        config: AgentConfig,
        *,
        agent_id: str | None = None,
        root_agent_id: str | None = None,
        parent_id: str | None = None,
        depth: int = 0,
        status: AgentStatus = AgentStatus.PENDING,
        turn_count: int = 0,
    ) -> Agent:
        new_agent_id = agent_id or str(uuid.uuid4())
        entity = AgentModel(
            id=new_agent_id,
            session_id=session_id,
            root_agent_id=root_agent_id or new_agent_id,
            parent_id=parent_id,
            depth=depth,
            status=status.value,
            model=config.model,
            task=config.task,
            tool_names=list(config.tool_names),
            turn_count=turn_count,
        )
        with self._session_factory() as session:
            session.add(entity)
            session.commit()
            session.refresh(entity)
            return self._to_domain(entity)

    def get_by_id(self, agent_id: str) -> Agent | None:
        with self._session_factory() as session:
            entity = session.get(AgentModel, agent_id)
            return self._to_domain(entity) if entity else None

    def list_all(self) -> list[Agent]:
        with self._session_factory() as session:
            entities = session.scalars(select(AgentModel).order_by(AgentModel.created_at)).all()
            return [self._to_domain(entity) for entity in entities]

    def list_by_session(self, session_id: str) -> list[Agent]:
        with self._session_factory() as session:
            entities = session.scalars(
                select(AgentModel)
                .where(AgentModel.session_id == session_id)
                .order_by(AgentModel.created_at)
            ).all()
            return [self._to_domain(entity) for entity in entities]

    def update(self, agent: Agent) -> Agent:
        with self._session_factory() as session:
            entity = session.get(AgentModel, agent.id)
            if entity is None:
                raise ValueError(f"Agent {agent.id} does not exist.")

            entity.session_id = agent.session_id
            entity.root_agent_id = agent.root_agent_id
            entity.parent_id = agent.parent_id
            entity.depth = agent.depth
            entity.status = agent.status.value
            entity.model = agent.config.model
            entity.task = agent.config.task
            entity.tool_names = list(agent.config.tool_names)
            entity.turn_count = agent.turn_count
            session.commit()
            session.refresh(entity)
            return self._to_domain(entity)

    def delete(self, agent_id: str) -> bool:
        with self._session_factory() as session:
            entity = session.get(AgentModel, agent_id)
            if entity is None:
                return False
            session.delete(entity)
            session.commit()
            return True

    @staticmethod
    def _to_domain(entity: AgentModel) -> Agent:
        return Agent(
            id=entity.id,
            session_id=entity.session_id,
            root_agent_id=entity.root_agent_id,
            parent_id=entity.parent_id,
            depth=entity.depth,
            status=AgentStatus(entity.status),
            turn_count=entity.turn_count,
            config=AgentConfig(
                model=entity.model,
                task=entity.task,
                tool_names=tuple(entity.tool_names or []),
            ),
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )
