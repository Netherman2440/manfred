from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.events.definitions.base import BaseEvent


@dataclass(slots=True, frozen=True)
class ToolFailedEvent(BaseEvent):
    call_id: str
    name: str
    arguments: dict[str, Any]
    error: str
    duration_ms: int
    start_time: datetime
    type: str = field(init=False, default="tool.failed")
