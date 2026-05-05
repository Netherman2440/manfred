from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True, frozen=True)
class QueuedInputAttachment:
    file_name: str
    media_type: str
    size_bytes: int
    path: str


@dataclass(slots=True)
class QueuedInput:
    id: str
    session_id: str
    agent_id: str
    message: str
    attachments: list[QueuedInputAttachment] = field(default_factory=list)
    accepted_at: datetime | None = None
    consumed_at: datetime | None = None
