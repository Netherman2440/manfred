from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain import Attachment
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
    status: Literal["completed", "failed"]
    output: list[OutputItemPayload]
    attachments: list[AttachmentPayload] = Field(default_factory=list)
    error: str | None = None


class AttachmentUploadResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="sessionId")
    attachments: list[AttachmentPayload]
