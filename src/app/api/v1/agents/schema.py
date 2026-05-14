from __future__ import annotations

from pydantic import BaseModel, Field

from app.api.v1.users.schema import SessionListEntrySchema


class AgentSummarySchema(BaseModel):
    name: str
    color: str | None
    description: str | None


class AgentDetailSchema(BaseModel):
    name: str
    color: str | None
    description: str | None
    model: str | None
    system_prompt: str
    tools: list[str]


class AgentCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=48)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    description: str | None = Field(default=None, max_length=500)
    model: str | None = None
    tools: list[str] = Field(default_factory=list)
    system_prompt: str = Field(default="", max_length=20000)


class AgentUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=48)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    description: str | None = Field(default=None, max_length=500)
    model: str | None = None
    tools: list[str] = Field(default_factory=list)
    system_prompt: str = Field(default="", max_length=20000)


class AgentsListResponse(BaseModel):
    data: list[AgentSummarySchema]


class AgentDetailResponse(BaseModel):
    data: AgentDetailSchema


class AgentSessionsResponse(BaseModel):
    data: list[SessionListEntrySchema]
