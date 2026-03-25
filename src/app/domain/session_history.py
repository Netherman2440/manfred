from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, TypeAlias

from app.domain.agent import WaitingFor
from app.domain.attachment import Attachment
from app.domain.chat import ChatOutputItem
from app.domain.types import SessionStatus


@dataclass(slots=True, frozen=True)
class SessionListItem:
    id: str
    root_agent_id: str | None
    status: SessionStatus
    summary: str
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, frozen=True)
class SessionListResponse:
    sessions: list[SessionListItem] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class SessionHistoryMessageEntry:
    item_id: str
    message: str
    created_at: datetime
    attachments: list[Attachment] = field(default_factory=list)
    type: Literal["message"] = "message"


@dataclass(slots=True, frozen=True)
class SessionHistoryAgentResponseEntry:
    agent_id: str
    model: str
    status: Literal["completed", "waiting", "failed"]
    created_at: datetime
    output: list[ChatOutputItem] = field(default_factory=list)
    waiting_for: list[WaitingFor] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    error: str | None = None
    type: Literal["agent_response"] = "agent_response"


SessionHistoryEntry: TypeAlias = SessionHistoryMessageEntry | SessionHistoryAgentResponseEntry


@dataclass(slots=True, frozen=True)
class SessionDetailResponse:
    session_id: str
    root_agent_id: str | None
    status: SessionStatus
    summary: str
    created_at: datetime
    updated_at: datetime
    entries: list[SessionHistoryEntry] = field(default_factory=list)
