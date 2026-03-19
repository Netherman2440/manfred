from dataclasses import dataclass, replace
from datetime import datetime

from app.domain.types import AgentStatus


@dataclass(slots=True, frozen=True)
class AgentConfig:
    model: str
    task: str #system_prompt
    tool_names: tuple[str, ...] = ()


@dataclass(slots=True)
class Agent:
    id: str
    session_id: str
    root_agent_id: str
    parent_id: str | None
    depth: int
    status: AgentStatus
    turn_count: int
    config: AgentConfig
    created_at: datetime
    updated_at: datetime


def prepare_agent_for_next_turn(agent: Agent, *, config: AgentConfig | None = None) -> Agent:
    # TODO: Replace with explicit transition rules when full agent status control lands.
    return replace(agent, status=AgentStatus.PENDING, config=config or agent.config)


def start_agent(agent: Agent) -> Agent:
    return replace(agent, status=AgentStatus.RUNNING)


def complete_agent(agent: Agent) -> Agent:
    return replace(agent, status=AgentStatus.COMPLETED)


def fail_agent(agent: Agent) -> Agent:
    return replace(agent, status=AgentStatus.FAILED)


def increment_agent_turn(agent: Agent) -> Agent:
    return replace(agent, turn_count=agent.turn_count + 1)
