from __future__ import annotations

from dataclasses import dataclass, field

from app.events.definitions.base import BaseEvent


@dataclass(slots=True, frozen=True)
class ReflectionStartedEvent(BaseEvent):
    agent_name: str
    token_count: int
    type: str = field(init=False, default="reflection.started")
