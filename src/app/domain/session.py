from dataclasses import dataclass
from datetime import datetime

from app.domain.types import SessionStatus


@dataclass(slots=True)
class Session:
    id: str
    user_id: str
    root_agent_id: str | None
    status: SessionStatus
    summary: str | None
    created_at: datetime
    updated_at: datetime
