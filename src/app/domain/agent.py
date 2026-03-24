from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal

from app.domain.types import AgentStatus


WaitType = Literal["tool", "agent", "human"]


@dataclass(slots=True, frozen=True)
class AgentConfig:
    model: str
    task: str
    tool_names: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class WaitingFor:
    call_id: str
    type: WaitType
    name: str
    description: str | None = None
    agent_id: str | None = None


@dataclass(slots=True)
class Agent:
    id: str
    session_id: str
    root_agent_id: str
    parent_id: str | None
    source_call_id: str | None
    depth: int
    status: AgentStatus
    waiting_for: tuple[WaitingFor, ...]
    result: Any | None
    error: str | None
    turn_count: int
    config: AgentConfig
    created_at: datetime
    updated_at: datetime


def prepare_agent_for_next_turn(agent: Agent, *, config: AgentConfig | None = None) -> Agent:
    if agent.status == AgentStatus.RUNNING:
        raise ValueError("Agent is already running.")
    if agent.status == AgentStatus.WAITING:
        raise ValueError("Agent is waiting for an external result.")

    return replace(
        agent,
        status=AgentStatus.PENDING,
        waiting_for=(),
        result=None,
        error=None,
        config=config or agent.config,
    )


def start_agent(agent: Agent) -> Agent:
    if agent.status != AgentStatus.PENDING:
        raise ValueError(f"Cannot start agent in status '{agent.status.value}'.")
    return replace(agent, status=AgentStatus.RUNNING)


def wait_for_many(agent: Agent, waiting_for: list[WaitingFor] | tuple[WaitingFor, ...]) -> Agent:
    if agent.status != AgentStatus.RUNNING:
        raise ValueError(f"Cannot put agent in waiting from status '{agent.status.value}'.")
    if len(waiting_for) == 0:
        raise ValueError("waiting_for must not be empty.")
    return replace(agent, status=AgentStatus.WAITING, waiting_for=tuple(waiting_for))


def deliver_one(agent: Agent, call_id: str) -> Agent:
    if agent.status != AgentStatus.WAITING:
        raise ValueError(f"Cannot deliver result to agent in status '{agent.status.value}'.")

    remaining = tuple(wait for wait in agent.waiting_for if wait.call_id != call_id)
    if len(remaining) == len(agent.waiting_for):
        raise ValueError(f"Agent is not waiting for call_id '{call_id}'.")

    new_status = AgentStatus.RUNNING if len(remaining) == 0 else AgentStatus.WAITING
    return replace(agent, status=new_status, waiting_for=remaining)


def complete_agent(agent: Agent, *, result: Any | None = None) -> Agent:
    if agent.status != AgentStatus.RUNNING:
        raise ValueError(f"Cannot complete agent in status '{agent.status.value}'.")
    return replace(
        agent,
        status=AgentStatus.COMPLETED,
        waiting_for=(),
        result=result,
        error=None,
    )


def fail_agent(agent: Agent, *, error: str | None = None) -> Agent:
    return replace(
        agent,
        status=AgentStatus.FAILED,
        waiting_for=(),
        error=error,
    )


def cancel_agent(agent: Agent) -> Agent:
    return replace(agent, status=AgentStatus.CANCELLED, waiting_for=())


def increment_agent_turn(agent: Agent) -> Agent:
    return replace(agent, turn_count=agent.turn_count + 1)
