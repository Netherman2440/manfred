from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.events.definitions.base import BaseEvent
from app.providers import ProviderInputItem, ProviderOutputItem, ProviderUsage


@dataclass(slots=True, frozen=True)
class GenerationCompletedEvent(BaseEvent):
    model: str
    instructions: str
    input: list[ProviderInputItem]
    output: list[ProviderOutputItem]
    usage: ProviderUsage | None
    duration_ms: int
    start_time: datetime
    type: str = field(init=False, default="generation.completed")
