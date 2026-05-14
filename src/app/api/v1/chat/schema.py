from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, Field


class MessageInputItem(BaseModel):
    type: Literal["message"] = "message"
    role: Literal["user", "assistant", "system"]
    content: str = Field(..., min_length=1)


ChatInputItem: TypeAlias = MessageInputItem


class FunctionToolDefinitionInput(BaseModel):
    type: Literal["function"] = "function"
    name: str = Field(..., min_length=1)
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class WebSearchToolDefinitionInput(BaseModel):
    type: Literal["web_search"] = "web_search"


ChatToolDefinitionInput = Annotated[
    FunctionToolDefinitionInput | WebSearchToolDefinitionInput,
    Field(discriminator="type"),
]


class ChatAgentConfigInput(BaseModel):
    agent_name: str | None = None
    model: str | None = None
    task: str | None = None
    tools: list[ChatToolDefinitionInput] | None = None
    temperature: float | None = None


class ChatRequest(BaseModel):
    input: list[ChatInputItem] = Field(default_factory=list)
    session_id: str | None = None
    stream: bool = False
    include_tool_result: bool = False
    agent_config: ChatAgentConfigInput | None = None


class AttachmentSchema(BaseModel):
    id: str
    file_name: str
    media_type: str
    size_bytes: int
    path: str


class ChatEditRequest(BaseModel):
    message: str = Field(..., min_length=1)
    stream: bool = False
    retain_attachment_ids: list[str] = Field(default_factory=list)


class ChatQueueRequest(BaseModel):
    message: str = Field(..., min_length=1)


class ChatQueueResponse(BaseModel):
    session_id: str
    queued_input_id: str
    accepted_at: datetime
    queue_position: int


class TextOutputItem(BaseModel):
    type: Literal["text"] = "text"
    text: str
    agent_id: str | None = None
    created_at: datetime | None = None


class FunctionCallOutputItem(BaseModel):
    type: Literal["function_call"] = "function_call"
    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    agent_id: str | None = None
    created_at: datetime | None = None


class FunctionCallResultOutputItem(BaseModel):
    type: Literal["function_call_output"] = "function_call_output"
    call_id: str
    name: str
    output: str | None = None
    is_error: bool = False
    agent_id: str | None = None
    created_at: datetime | None = None


class WaitingForOutputItem(BaseModel):
    call_id: str
    type: Literal["tool", "agent", "human"]
    name: str
    description: str | None = None
    agent_id: str | None = None


ChatOutputItem = Annotated[
    TextOutputItem | FunctionCallOutputItem | FunctionCallResultOutputItem,
    Field(discriminator="type"),
]


class ChatResponse(BaseModel):
    id: str
    agent_id: str
    session_id: str
    status: Literal["completed", "waiting", "failed", "cancelled"]
    model: str
    output: list[ChatOutputItem] = Field(default_factory=list)
    waiting_for: list[WaitingForOutputItem] = Field(default_factory=list)
    error: str | None = None


class DeliverRequest(BaseModel):
    call_id: str = Field(..., min_length=1)
    output: Any = None
    is_error: bool = False


@dataclass(slots=True, frozen=True)
class ChatStreamSessionEvent:
    session_id: str
    agent_id: str
    type: str = field(init=False, default="session")
