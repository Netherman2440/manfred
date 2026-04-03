from __future__ import annotations

from dataclasses import dataclass, field

from app.events.definitions.base import BaseEvent


@dataclass(slots=True, frozen=True)
class AgentFailedEvent(BaseEvent):
    error: str
    type: str = field(init=False, default="agent.failed")
