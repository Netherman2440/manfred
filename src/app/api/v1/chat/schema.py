from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain import (
    Attachment,
    SessionDetailResponse as DomainSessionDetailResponse,
    SessionHistoryAgentResponseEntry,
    SessionHistoryMessageEntry,
    SessionListItem as DomainSessionListItem,
    WaitingFor,
)
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


class FunctionCallResultOutputItemPayload(BaseModel):
    type: Literal["function_call_output"]
    call_id: str = Field(..., alias="callId")
    name: str
    output: Any
    is_error: bool = Field(..., alias="isError")


OutputItemPayload = TextOutputItemPayload | FunctionCallOutputItemPayload | FunctionCallResultOutputItemPayload


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


class SessionListItemPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    root_agent_id: str | None = Field(default=None, alias="rootAgentId")
    status: Literal["active", "archived"]
    summary: str
    created_at: str = Field(..., alias="createdAt")
    updated_at: str = Field(..., alias="updatedAt")

    @classmethod
    def from_domain(cls, session: DomainSessionListItem) -> "SessionListItemPayload":
        return cls(
            id=session.id,
            rootAgentId=session.root_agent_id,
            status=session.status.value,
            summary=session.summary,
            createdAt=session.created_at.isoformat(),
            updatedAt=session.updated_at.isoformat(),
        )


class SessionListResponse(BaseModel):
    sessions: list[SessionListItemPayload]


class SessionHistoryMessageEntryPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["message"]
    item_id: str = Field(..., alias="itemId")
    message: str
    created_at: str = Field(..., alias="createdAt")
    attachments: list[AttachmentPayload] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, entry: SessionHistoryMessageEntry) -> "SessionHistoryMessageEntryPayload":
        return cls(
            type=entry.type,
            itemId=entry.item_id,
            message=entry.message,
            createdAt=entry.created_at.isoformat(),
            attachments=[AttachmentPayload.from_domain(attachment) for attachment in entry.attachments],
        )


class SessionHistoryAgentResponseEntryPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["agent_response"]
    agent_id: str = Field(..., alias="agentId")
    model: str
    status: Literal["completed", "waiting", "failed"]
    created_at: str = Field(..., alias="createdAt")
    output: list[OutputItemPayload] = Field(default_factory=list)
    waiting_for: list[WaitingForPayload] = Field(default_factory=list, alias="waitingFor")
    attachments: list[AttachmentPayload] = Field(default_factory=list)
    error: str | None = None

    @classmethod
    def from_domain(
        cls,
        entry: SessionHistoryAgentResponseEntry,
    ) -> "SessionHistoryAgentResponseEntryPayload":
        return cls(
            type=entry.type,
            agentId=entry.agent_id,
            model=entry.model,
            status=entry.status,
            createdAt=entry.created_at.isoformat(),
            output=entry.output,
            waitingFor=[WaitingForPayload.from_domain(wait) for wait in entry.waiting_for],
            attachments=[AttachmentPayload.from_domain(attachment) for attachment in entry.attachments],
            error=entry.error,
        )


SessionHistoryEntryPayload = SessionHistoryMessageEntryPayload | SessionHistoryAgentResponseEntryPayload


class SessionDetailResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="sessionId")
    root_agent_id: str | None = Field(default=None, alias="rootAgentId")
    status: Literal["active", "archived"]
    summary: str
    created_at: str = Field(..., alias="createdAt")
    updated_at: str = Field(..., alias="updatedAt")
    entries: list[SessionHistoryEntryPayload] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, session: DomainSessionDetailResponse) -> "SessionDetailResponse":
        entries: list[SessionHistoryEntryPayload] = []
        for entry in session.entries:
            if isinstance(entry, SessionHistoryMessageEntry):
                entries.append(SessionHistoryMessageEntryPayload.from_domain(entry))
                continue
            entries.append(SessionHistoryAgentResponseEntryPayload.from_domain(entry))

        return cls(
            sessionId=session.session_id,
            rootAgentId=session.root_agent_id,
            status=session.status.value,
            summary=session.summary,
            createdAt=session.created_at.isoformat(),
            updatedAt=session.updated_at.isoformat(),
            entries=entries,
        )


ChatResponse.model_rebuild()
