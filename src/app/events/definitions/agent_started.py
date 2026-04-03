from __future__ import annotations

from dataclasses import dataclass, field

from app.events.definitions.base import BaseEvent


@dataclass(slots=True, frozen=True)
class AgentStartedEvent(BaseEvent):
    model: str
    task: str
    agent_name: str | None = None
    user_id: str | None = None
    user_input: str | None = None
    type: str = field(init=False, default="agent.started")
