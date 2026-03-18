from dataclasses import dataclass
from datetime import datetime

from app.domain.types import ItemType, MessageRole


@dataclass(slots=True)
class Item:
    id: str
    session_id: str
    agent_id: str
    sequence: int
    type: ItemType
    role: MessageRole | None
    content: str | None
    call_id: str | None
    name: str | None
    arguments_json: str | None
    output: str | None
    is_error: bool
    created_at: datetime
