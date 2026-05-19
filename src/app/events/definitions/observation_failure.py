from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.events.definitions.base import BaseEvent


@dataclass(slots=True, frozen=True)
class ObservationFailureEvent(BaseEvent):
    agent_name: str
    reason: Literal["locked", "error"]
    detail: str | None = None
    type: str = field(init=False, default="observation.failure")
