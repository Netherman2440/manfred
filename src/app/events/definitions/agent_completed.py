from __future__ import annotations

from dataclasses import dataclass, field

from app.events.definitions.base import BaseEvent
from app.providers import ProviderUsage


@dataclass(slots=True, frozen=True)
class AgentCompletedEvent(BaseEvent):
    duration_ms: int
    usage: ProviderUsage | None = None
    result: str | None = None
    type: str = field(init=False, default="agent.completed")
