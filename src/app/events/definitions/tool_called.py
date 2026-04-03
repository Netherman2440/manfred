from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.events.definitions.base import BaseEvent


@dataclass(slots=True, frozen=True)
class ToolCalledEvent(BaseEvent):
    call_id: str
    name: str
    arguments: dict[str, Any]
    type: str = field(init=False, default="tool.called")
