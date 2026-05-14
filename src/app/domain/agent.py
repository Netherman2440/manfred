from dataclasses import dataclass
from datetime import datetime

from app.domain.tool import ToolDefinition
from app.domain.types import AgentStatus
from app.domain.waiting import WaitingForEntry


@dataclass(slots=True, frozen=True)
class AgentConfig:
    model: str
    task: str  # system_prompt
    tools: list[ToolDefinition] | None
    temperature: float | None


@dataclass(slots=True)
class Agent:
    id: str
    session_id: str
    trace_id: str | None
    root_agent_id: str
    parent_id: str | None
    source_call_id: str | None
    depth: int
    agent_name: str | None
    status: AgentStatus
    turn_count: int
    waiting_for: list[WaitingForEntry]
    config: AgentConfig
    created_at: datetime
    updated_at: datetime
