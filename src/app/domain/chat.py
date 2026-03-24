from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias, TypedDict

from app.domain.agent import Agent, WaitingFor
from app.domain.attachment import Attachment
from app.domain.item import Item
from app.domain.session import Session
from app.domain.tool import ToolDefinition
from app.domain.user import User


@dataclass(slots=True, frozen=True)
class ChatRequest:
    message: str
    session_id: str | None = None
    attachment_ids: tuple[str, ...] = ()


@dataclass(slots=True)
class ChatTurn:
    user: User
    session: Session
    agent: Agent
    user_item: Item
    trace_id: str
    response_start_sequence: int
    attachments: list[Attachment] = field(default_factory=list)
    tools: list[ToolDefinition] = field(default_factory=list)


class ChatTextOutput(TypedDict):
    type: Literal["text"]
    text: str


class ChatFunctionCallOutput(TypedDict):
    type: Literal["function_call"]
    callId: str
    name: str
    arguments: dict[str, Any]


ChatOutputItem: TypeAlias = ChatTextOutput | ChatFunctionCallOutput


@dataclass(slots=True, frozen=True)
class ChatResponse:
    user_id: str
    session_id: str
    agent_id: str
    model: str
    status: Literal["completed", "waiting", "failed"]
    output: list[ChatOutputItem] = field(default_factory=list)
    waiting_for: list[WaitingFor] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    error: str | None = None


@dataclass(slots=True, frozen=True)
class AgentState:
    agent_id: str
    session_id: str
    root_agent_id: str
    parent_id: str | None
    source_call_id: str | None
    model: str
    status: Literal["pending", "running", "waiting", "completed", "failed", "cancelled"]
    depth: int
    turn_count: int
    waiting_for: list[WaitingFor] = field(default_factory=list)
    result: Any | None = None
    error: str | None = None
