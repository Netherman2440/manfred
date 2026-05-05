from dataclasses import dataclass, field
from datetime import datetime

from app.domain.types import ItemType, MessageRole


@dataclass(slots=True)
class Attachment:
    id: str
    item_id: str
    file_name: str
    media_type: str
    size_bytes: int
    path: str
    created_at: datetime


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
    attachments: list[Attachment] = field(default_factory=list)
    edited_at: datetime | None = None
