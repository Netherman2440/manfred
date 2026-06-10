"""Runtime-level stream events bridged onto the chat SSE stream.

These complement the provider (LLM-layer) stream events. They carry tool
results and terminal agent status so a streaming client never has to poll
session detail to learn what happened. Emitted in-order by
``Runner.run_agent_stream`` alongside provider events.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain import WaitingForEntry


@dataclass(slots=True, frozen=True)
class ToolCompletedStreamEvent:
    call_id: str
    name: str
    output: dict[str, Any]
    type: str = "tool.completed"


@dataclass(slots=True, frozen=True)
class ToolFailedStreamEvent:
    call_id: str
    name: str
    error: str
    type: str = "tool.failed"


@dataclass(slots=True, frozen=True)
class AgentWaitingStreamEvent:
    waiting_for: list[WaitingForEntry]
    type: str = "agent.waiting"


@dataclass(slots=True, frozen=True)
class AgentCompletedStreamEvent:
    agent_id: str
    type: str = "agent.completed"


@dataclass(slots=True, frozen=True)
class AgentFailedStreamEvent:
    agent_id: str
    error: str
    type: str = "agent.failed"


@dataclass(slots=True, frozen=True)
class AgentCancelledStreamEvent:
    agent_id: str
    type: str = "agent.cancelled"


RuntimeStreamEvent = (
    ToolCompletedStreamEvent
    | ToolFailedStreamEvent
    | AgentWaitingStreamEvent
    | AgentCompletedStreamEvent
    | AgentFailedStreamEvent
    | AgentCancelledStreamEvent
)


def serialize_runtime_stream_event(event: RuntimeStreamEvent) -> dict[str, Any]:
    if isinstance(event, ToolCompletedStreamEvent):
        return {
            "type": event.type,
            "call_id": event.call_id,
            "name": event.name,
            "output": event.output,
        }

    if isinstance(event, ToolFailedStreamEvent):
        return {
            "type": event.type,
            "call_id": event.call_id,
            "name": event.name,
            "error": event.error,
        }

    if isinstance(event, AgentWaitingStreamEvent):
        return {
            "type": event.type,
            "waiting_for": [entry.to_dict() for entry in event.waiting_for],
        }

    if isinstance(event, AgentCompletedStreamEvent):
        return {
            "type": event.type,
            "agent_id": event.agent_id,
        }

    if isinstance(event, AgentFailedStreamEvent):
        return {
            "type": event.type,
            "agent_id": event.agent_id,
            "error": event.error,
        }

    return {
        "type": event.type,
        "agent_id": event.agent_id,
    }
