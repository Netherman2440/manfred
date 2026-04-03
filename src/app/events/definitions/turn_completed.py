from __future__ import annotations

from dataclasses import dataclass, field

from app.events.definitions.base import BaseEvent
from app.providers import ProviderUsage


@dataclass(slots=True, frozen=True)
class TurnCompletedEvent(BaseEvent):
    turn_count: int
    usage: ProviderUsage | None = None
    type: str = field(init=False, default="turn.completed")
