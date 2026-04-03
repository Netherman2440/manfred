from __future__ import annotations

from dataclasses import dataclass, field

from app.events.definitions.base import BaseEvent


@dataclass(slots=True, frozen=True)
class TurnStartedEvent(BaseEvent):
    turn_count: int
    type: str = field(init=False, default="turn.started")
