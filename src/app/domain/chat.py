from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias, TypedDict

from app.domain.agent import Agent
from app.domain.item import Item
from app.domain.session import Session
from app.domain.tool import ToolDefinition
from app.domain.user import User


@dataclass(slots=True, frozen=True)
class ChatRequest:
    message: str
    session_id: str | None = None


@dataclass(slots=True)
class ChatTurn:
    user: User
    session: Session
    agent: Agent
    user_item: Item
    trace_id: str
    response_start_sequence: int
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
    status: Literal["completed", "failed"]
    output: list[ChatOutputItem] = field(default_factory=list)
    error: str | None = None
