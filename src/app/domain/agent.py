from dataclasses import dataclass
from datetime import datetime

from app.domain.tool import ToolDefinition
from app.domain.types import AgentStatus


@dataclass(slots=True, frozen=True)
class AgentConfig:
    model: str
    task: str #system_prompt
    tools: list[ToolDefinition] | None
    temperature: float | None


@dataclass(slots=True)
class Agent:
    id: str
    session_id: str
    root_agent_id: str
    parent_id: str | None
    depth: int
    agent_name: str | None
    status: AgentStatus
    turn_count: int
    config: AgentConfig
    created_at: datetime
    updated_at: datetime
