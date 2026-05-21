from __future__ import annotations

from dataclasses import dataclass, field

from app.events.definitions.base import BaseEvent


@dataclass(slots=True, frozen=True)
class ObservationStartedEvent(BaseEvent):
    agent_name: str
    message_count: int
    token_count: int
    type: str = field(init=False, default="observation.started")
