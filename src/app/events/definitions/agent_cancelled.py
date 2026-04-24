from __future__ import annotations

from dataclasses import dataclass, field

from app.events.definitions.base import BaseEvent


@dataclass(slots=True, frozen=True)
class AgentCancelledEvent(BaseEvent):
    type: str = field(init=False, default="agent.cancelled")
