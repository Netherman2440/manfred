from __future__ import annotations

from dataclasses import dataclass, field

from app.domain import WaitingForEntry
from app.events.definitions.base import BaseEvent


@dataclass(slots=True, frozen=True)
class AgentResumedEvent(BaseEvent):
    call_id: str
    waiting_for: list[WaitingForEntry]
    type: str = field(init=False, default="agent.resumed")
