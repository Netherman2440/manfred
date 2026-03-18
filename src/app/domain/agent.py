from dataclasses import dataclass, field
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
