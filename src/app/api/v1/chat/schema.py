from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain import ChatRequest as DomainChatRequest


class ChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message: str = Field(..., min_length=1)
    session_id: str | None = Field(default=None, alias="sessionId")

    def to_domain(self) -> DomainChatRequest:
        return DomainChatRequest(
            message=self.message,
            session_id=self.session_id,
        )


class TextOutputItemPayload(BaseModel):
    type: Literal["text"]
    text: str


class FunctionCallOutputItemPayload(BaseModel):
    type: Literal["function_call"]
    call_id: str = Field(..., alias="callId")
    name: str
    arguments: dict[str, Any]


OutputItemPayload = TextOutputItemPayload | FunctionCallOutputItemPayload


class ChatResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: str = Field(..., alias="userId")
    session_id: str = Field(..., alias="sessionId")
    agent_id: str = Field(..., alias="agentId")
    model: str
    status: Literal["completed", "failed"]
    output: list[OutputItemPayload]
    error: str | None = None
