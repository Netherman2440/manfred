from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.events.definitions.base import BaseEvent


@dataclass(slots=True, frozen=True)
class ToolCompletedEvent(BaseEvent):
    call_id: str
    name: str
    arguments: dict[str, Any]
    output: dict[str, Any]
    duration_ms: int
    start_time: datetime
    type: str = field(init=False, default="tool.completed")
