from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class SessionListEntrySchema(BaseModel):
    id: str
    user_id: str
    title: str | None = None
    status: Literal["active", "archived"]
    root_agent_id: str
    root_agent_name: str
    root_agent_status: Literal[
        "pending",
        "running",
        "waiting",
        "completed",
        "failed",
        "cancelled",
    ]
    waiting_for_count: int = 0
    last_message_preview: str | None = None
    created_at: datetime
    updated_at: datetime


class UserSessionsResponse(BaseModel):
    data: list[SessionListEntrySchema] = Field(default_factory=list)


class SessionSummarySchema(BaseModel):
    id: str
    user_id: str
    title: str | None = None
    status: Literal["active", "archived"]
    created_at: datetime
    updated_at: datetime


class WaitingForSchema(BaseModel):
    call_id: str
    type: Literal["tool", "agent", "human"]
    name: str
    description: str | None = None
    agent_id: str | None = None


class RootAgentSchema(BaseModel):
    id: str
    name: str
    status: Literal[
        "pending",
        "running",
        "waiting",
        "completed",
        "failed",
        "cancelled",
    ]
    model: str
    waiting_for: list[WaitingForSchema] = Field(default_factory=list)


class SessionMessageItemSchema(BaseModel):
    id: str
    sequence: int
    agent_id: str
    type: Literal["message"] = "message"
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: datetime


class SessionFunctionCallItemSchema(BaseModel):
    id: str
    sequence: int
    agent_id: str
    type: Literal["function_call"] = "function_call"
    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class SessionFunctionCallOutputItemSchema(BaseModel):
    id: str
    sequence: int
    agent_id: str
    type: Literal["function_call_output"] = "function_call_output"
    call_id: str
    name: str
    tool_result: dict[str, Any] = Field(default_factory=dict)
    is_error: bool = False
    created_at: datetime


class SessionReasoningItemSchema(BaseModel):
    id: str
    sequence: int
    agent_id: str
    type: Literal["reasoning"] = "reasoning"
    content: str | None = None
    created_at: datetime


SessionItemSchema = Annotated[
    SessionMessageItemSchema
    | SessionFunctionCallItemSchema
    | SessionFunctionCallOutputItemSchema
    | SessionReasoningItemSchema,
    Field(discriminator="type"),
]


class SessionDetailPayloadSchema(BaseModel):
    session: SessionSummarySchema
    root_agent: RootAgentSchema
    items: list[SessionItemSchema] = Field(default_factory=list)


class SessionDetailResponse(BaseModel):
    data: SessionDetailPayloadSchema
