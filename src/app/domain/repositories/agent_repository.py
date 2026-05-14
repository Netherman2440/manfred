from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AgentModel
from app.domain.agent import Agent, AgentConfig
from app.domain.tool import FunctionToolDefinition, ToolDefinition, WebSearchToolDefinition
from app.domain.types import AgentStatus
from app.domain.waiting import WaitingForEntry


class AgentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, agent_id: str) -> Agent | None:
        model = self.session.get(AgentModel, agent_id)
        return None if model is None else self._to_domain(model)

    def list_by_session(self, session_id: str) -> list[Agent]:
        models = self.session.scalars(
            select(AgentModel).where(AgentModel.session_id == session_id).order_by(AgentModel.created_at.asc())
        ).all()
        return [self._to_domain(model) for model in models]

    def list_children(self, parent_id: str) -> list[Agent]:
        models = self.session.scalars(
            select(AgentModel).where(AgentModel.parent_id == parent_id).order_by(AgentModel.created_at.asc())
        ).all()
        return [self._to_domain(model) for model in models]

    def get_child_by_source_call(self, parent_id: str, source_call_id: str) -> Agent | None:
        model = self.session.scalar(
            select(AgentModel)
            .where(
                AgentModel.parent_id == parent_id,
                AgentModel.source_call_id == source_call_id,
            )
            .order_by(AgentModel.created_at.desc())
        )
        return None if model is None else self._to_domain(model)

    def save(self, agent: Agent) -> Agent:
        model = self.session.get(AgentModel, agent.id)
        if model is None:
            model = AgentModel(id=agent.id)

        model.session_id = agent.session_id
        model.trace_id = agent.trace_id
        model.root_agent_id = agent.root_agent_id
        model.parent_id = agent.parent_id
        model.source_call_id = agent.source_call_id
        model.depth = agent.depth
        model.agent_name = agent.agent_name
        model.status = agent.status.value
        model.model = agent.config.model
        model.task = agent.config.task
        model.config = self._serialize_config(agent.config)
        model.waiting_for = self._serialize_waiting_for(agent.waiting_for)
        model.turn_count = agent.turn_count
        model.created_at = agent.created_at
        model.updated_at = agent.updated_at

        self.session.add(model)
        self.session.flush()
        return self._to_domain(model)

    def delete_many(self, agent_ids: list[str]) -> None:
        if not agent_ids:
            return
        models = self.session.scalars(select(AgentModel).where(AgentModel.id.in_(agent_ids))).all()
        for model in models:
            self.session.delete(model)
        self.session.flush()

    def _to_domain(self, model: AgentModel) -> Agent:
        config_payload = model.config or {}
        return Agent(
            id=model.id,
            session_id=model.session_id,
            trace_id=model.trace_id,
            root_agent_id=model.root_agent_id,
            parent_id=model.parent_id,
            source_call_id=model.source_call_id,
            depth=model.depth,
            agent_name=model.agent_name,
            status=AgentStatus(model.status),
            turn_count=model.turn_count,
            waiting_for=self._deserialize_waiting_for(model.waiting_for),
            config=AgentConfig(
                model=model.model,
                task=model.task,
                tools=self._deserialize_tools(config_payload.get("tools")),
                temperature=config_payload.get("temperature"),
            ),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    @staticmethod
    def _serialize_config(config: AgentConfig) -> dict[str, Any]:
        return {
            "tools": [AgentRepository._serialize_tool(tool) for tool in config.tools] if config.tools else [],
            "temperature": config.temperature,
        }

    @staticmethod
    def _serialize_tool(tool: ToolDefinition) -> dict[str, Any]:
        if isinstance(tool, FunctionToolDefinition):
            return {
                "type": tool.type,
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
        return {"type": tool.type}

    @staticmethod
    def _deserialize_tools(payload: Any) -> list[ToolDefinition]:
        if not isinstance(payload, list):
            return []

        tools: list[ToolDefinition] = []
        for item in payload:
            if not isinstance(item, dict):
                continue

            if item.get("type") == "web_search":
                tools.append(WebSearchToolDefinition())
                continue

            tools.append(
                FunctionToolDefinition(
                    name=str(item.get("name", "")),
                    description=str(item.get("description", "")),
                    parameters=dict(item.get("parameters") or {}),
                )
            )
        return tools

    @staticmethod
    def _serialize_waiting_for(waiting_for: list[WaitingForEntry]) -> list[dict[str, Any]]:
        return [entry.to_dict() for entry in waiting_for]

    @staticmethod
    def _deserialize_waiting_for(payload: Any) -> list[WaitingForEntry]:
        if not isinstance(payload, list):
            return []

        waiting_for: list[WaitingForEntry] = []
        for item in payload:
            entry = WaitingForEntry.from_dict(item)
            if entry is not None:
                waiting_for.append(entry)
        return waiting_for
