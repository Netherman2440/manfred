from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain import Attachment, WaitingFor
from app.domain import ChatRequest as DomainChatRequest


class ChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message: str = ""
    session_id: str | None = Field(default=None, alias="sessionId")
    attachment_ids: list[str] = Field(default_factory=list, alias="attachmentIds")

    @model_validator(mode="after")
    def validate_message_or_attachments(self) -> "ChatRequest":
        if self.message.strip() == "" and not self.attachment_ids:
            raise ValueError("message must not be empty when no attachments are provided.")
        return self

    def to_domain(self) -> DomainChatRequest:
        return DomainChatRequest(
            message=self.message,
            session_id=self.session_id,
            attachment_ids=tuple(self.attachment_ids),
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


class AttachmentTranscriptionPayload(BaseModel):
    status: Literal["not_applicable", "pending", "completed", "failed"]
    text: str | None = None


class AttachmentPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    kind: Literal["image", "document", "audio", "other"]
    mime_type: str = Field(..., alias="mimeType")
    original_filename: str = Field(..., alias="originalFilename")
    workspace_path: str = Field(..., alias="workspacePath")
    size_bytes: int = Field(..., alias="sizeBytes")
    transcription: AttachmentTranscriptionPayload

    @classmethod
    def from_domain(cls, attachment: Attachment) -> "AttachmentPayload":
        return cls(
            id=attachment.id,
            kind=attachment.kind.value,
            mimeType=attachment.mime_type,
            originalFilename=attachment.original_filename,
            workspacePath=attachment.workspace_path,
            sizeBytes=attachment.size_bytes,
            transcription=AttachmentTranscriptionPayload(
                status=attachment.transcription_status.value,
                text=attachment.transcription_text,
            ),
        )


class ChatResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: str = Field(..., alias="userId")
    session_id: str = Field(..., alias="sessionId")
    agent_id: str = Field(..., alias="agentId")
    model: str
    status: Literal["completed", "waiting", "failed"]
    output: list[OutputItemPayload]
    waiting_for: list["WaitingForPayload"] = Field(default_factory=list, alias="waitingFor")
    attachments: list[AttachmentPayload] = Field(default_factory=list)
    error: str | None = None


class AttachmentUploadResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="sessionId")
    attachments: list[AttachmentPayload]


class WaitingForPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    call_id: str = Field(..., alias="callId")
    type: Literal["tool", "agent", "human"]
    name: str
    description: str | None = None
    agent_id: str | None = Field(default=None, alias="agentId")

    @classmethod
    def from_domain(cls, waiting: WaitingFor) -> "WaitingForPayload":
        return cls(
            callId=waiting.call_id,
            type=waiting.type,
            name=waiting.name,
            description=waiting.description,
            agentId=waiting.agent_id,
        )


class DeliverRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    call_id: str = Field(..., alias="callId")
    output: Any
    is_error: bool = Field(default=False, alias="isError")


class AgentStateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    agent_id: str = Field(..., alias="agentId")
    session_id: str = Field(..., alias="sessionId")
    root_agent_id: str = Field(..., alias="rootAgentId")
    parent_id: str | None = Field(default=None, alias="parentId")
    source_call_id: str | None = Field(default=None, alias="sourceCallId")
    model: str
    status: Literal["pending", "running", "waiting", "completed", "failed", "cancelled"]
    depth: int
    turn_count: int = Field(..., alias="turnCount")
    waiting_for: list[WaitingForPayload] = Field(default_factory=list, alias="waitingFor")
    result: Any | None = None
    error: str | None = None


ChatResponse.model_rebuild()
