from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from app.db.base import utcnow
from app.domain import Agent


@dataclass(slots=True, frozen=True)
class EventContext:
    event_id: str
    timestamp: datetime
    trace_id: str
    session_id: str
    agent_id: str
    agent_name: str | None
    root_agent_id: str
    parent_agent_id: str | None
    depth: int


@dataclass(slots=True, frozen=True)
class BaseEvent:
    ctx: EventContext


def build_event_context(agent: Agent, trace_id: str) -> EventContext:
    return EventContext(
        event_id=uuid4().hex,
        timestamp=utcnow(),
        trace_id=trace_id,
        session_id=agent.session_id,
        agent_id=agent.id,
        agent_name=agent.agent_name,
        root_agent_id=agent.root_agent_id,
        parent_agent_id=agent.parent_id,
        depth=agent.depth,
    )
